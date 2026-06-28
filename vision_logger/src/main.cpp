#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <print>
#include <string>
#include <thread>

#include "common/batch_writer.hpp"
#include "common/blocking_queue.hpp"
#include "common/config.hpp"
#include "common/signal.hpp"
#include "common/sql_format.hpp"
#include "common/timestamp.hpp"
#include "common/udp_receiver.hpp"

#include "messages_robocup_ssl_wrapper.pb.h"

namespace {

// ---- Row types ------------------------------------------------------------
struct RobotDet {
    common::RxTime rx;
    double t_capture = 0, t_sent = 0;
    int64_t frame_number = 0;
    int camera_id = 0;
    int team = 0;                       // 0 = blue, 1 = yellow
    std::optional<long long> robot_id;
    float x = 0, y = 0, confidence = 0;
    std::optional<double> orientation;
};

struct BallDet {
    common::RxTime rx;
    double t_capture = 0, t_sent = 0;
    int64_t frame_number = 0;
    int camera_id = 0;
    float x = 0, y = 0, confidence = 0;
};

const char* kRobotCols =
    "rx_wall, rx_monotonic, t_capture, t_sent, frame_number, camera_id, "
    "team, robot_id, x, y, orientation, confidence";
const char* kBallCols =
    "rx_wall, rx_monotonic, t_capture, t_sent, frame_number, camera_id, "
    "x, y, confidence";

std::string format_robot(const RobotDet& r) {
    std::string s = "(";
    s += common::sql_timestamp(r.rx.wall);                 s += ',';
    s += common::sql_float(r.rx.monotonic);                s += ',';
    s += common::sql_float(r.t_capture);                   s += ',';
    s += common::sql_float(r.t_sent);                      s += ',';
    s += common::sql_int(r.frame_number);                  s += ',';
    s += common::sql_int(r.camera_id);                     s += ',';
    s += common::sql_int(r.team);                          s += ',';
    s += common::sql_int(r.robot_id);                      s += ',';
    s += common::sql_float(r.x);                           s += ',';
    s += common::sql_float(r.y);                           s += ',';
    s += common::sql_float(r.orientation);                 s += ',';
    s += common::sql_float(r.confidence);                  s += ')';
    return s;
}

std::string format_ball(const BallDet& b) {
    std::string s = "(";
    s += common::sql_timestamp(b.rx.wall);                 s += ',';
    s += common::sql_float(b.rx.monotonic);                s += ',';
    s += common::sql_float(b.t_capture);                   s += ',';
    s += common::sql_float(b.t_sent);                      s += ',';
    s += common::sql_int(b.frame_number);                  s += ',';
    s += common::sql_int(b.camera_id);                     s += ',';
    s += common::sql_float(b.x);                           s += ',';
    s += common::sql_float(b.y);                           s += ',';
    s += common::sql_float(b.confidence);                  s += ')';
    return s;
}

}  // namespace

int main() {
    GOOGLE_PROTOBUF_VERIFY_VERSION;

    std::atomic<bool> stop{false};
    common::install_shutdown_handler(&stop);

    if (common::load_dotenv()) std::println("config: loaded .env");

    const std::string group = common::env_str("VISION_MCAST_GROUP", "224.5.23.2");
    const int port = common::env_int("VISION_MCAST_PORT", 10006);
    const std::string iface = common::env_str("VISION_MCAST_IFACE", "0.0.0.0");
    const std::string conninfo = common::env_str(
        "DB_CONNINFO",
        "host=localhost port=5432 dbname=robot_data user=robot_writer");
    const int batch = common::env_int("DB_BATCH_SIZE", 100);
    const int latency_ms = common::env_int("DB_MAX_LATENCY_MS", 200);
    const auto latency = std::chrono::milliseconds(latency_ms);

    common::BlockingQueue<RobotDet> robot_q;
    common::BlockingQueue<BallDet> ball_q;
    common::BatchWriter<RobotDet> robot_writer(conninfo, "vision.robot_detection",
                                               kRobotCols, format_robot, batch,
                                               latency);
    common::BatchWriter<BallDet> ball_writer(conninfo, "vision.ball_detection",
                                             kBallCols, format_ball, batch,
                                             latency);
    std::jthread robot_worker([&] { robot_writer.run(robot_q, stop); });
    std::jthread ball_worker([&] { ball_writer.run(ball_q, stop); });

    std::println(
        "vision_logger: listening on {}:{} -> vision.{{robot,ball}}_detection",
        group, port);

    auto handle_robots = [&](const common::RxTime& rx, const SSL_DetectionFrame& d,
                             const auto& robots, int team, uint64_t& counter) {
        for (const auto& rb : robots) {
            RobotDet r;
            r.rx = rx;
            r.t_capture = d.t_capture();
            r.t_sent = d.t_sent();
            r.frame_number = d.frame_number();
            r.camera_id = d.camera_id();
            r.team = team;
            if (rb.has_robot_id()) r.robot_id = rb.robot_id();
            r.x = rb.x();
            r.y = rb.y();
            r.confidence = rb.confidence();
            if (rb.has_orientation()) r.orientation = rb.orientation();
            robot_q.push(r);
            ++counter;
        }
    };

    int rc = 0;
    try {
        common::UdpReceiver sock(group, static_cast<uint16_t>(port), iface);
        uint8_t buf[65536];

        uint64_t frames = 0, robots = 0, balls = 0;
        auto last_report = std::chrono::steady_clock::now();

        while (!stop.load()) {
            ssize_t n = sock.recv(buf, sizeof(buf));
            if (n <= 0) continue;
            common::RxTime rx = common::now_rx();

            SSL_WrapperPacket pkt;
            if (!pkt.ParseFromArray(buf, static_cast<int>(n))) continue;
            if (!pkt.has_detection()) continue;  // skip geometry-only frames
            const SSL_DetectionFrame& d = pkt.detection();
            ++frames;

            handle_robots(rx, d, d.robots_blue(), 0, robots);
            handle_robots(rx, d, d.robots_yellow(), 1, robots);

            for (const auto& bl : d.balls()) {
                BallDet b;
                b.rx = rx;
                b.t_capture = d.t_capture();
                b.t_sent = d.t_sent();
                b.frame_number = d.frame_number();
                b.camera_id = d.camera_id();
                b.x = bl.x();
                b.y = bl.y();
                b.confidence = bl.confidence();
                ball_q.push(b);
                ++balls;
            }

            auto now = std::chrono::steady_clock::now();
            if (now - last_report >= std::chrono::seconds(1)) {
                std::println(stderr,
                             "[vision] frames={} robots={} balls={} "
                             "(rq={} bq={})",
                             frames, robots, balls, robot_q.size(),
                             ball_q.size());
                last_report = now;
            }
        }
    } catch (const std::exception& e) {
        std::println(stderr, "vision_logger fatal: {}", e.what());
        rc = 1;
    }

    // Clean shutdown: stop both workers and let them flush what is queued.
    stop.store(true);
    std::println("vision_logger: shutting down, flushing...");
    robot_worker.join();
    ball_worker.join();

    // Exit hard, skipping C++ global destructors: libpqxx 7.10 double-frees a
    // static std::string in its shared-library finalizers at exit (confirmed via
    // gdb). All rows are committed and both workers are joined.
    std::fflush(nullptr);
    std::quick_exit(rc);
}
