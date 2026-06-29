#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <print>
#include <span>
#include <string>
#include <thread>
#include <vector>

#include "common/batch_writer.hpp"
#include "common/blocking_queue.hpp"
#include "common/config.hpp"
#include "common/signal.hpp"
#include "common/sql_format.hpp"
#include "common/timestamp.hpp"
#include "common/udp_receiver.hpp"
#include "parser.hpp"

using robot::Telemetry;

namespace {

const char* kColumns =
    "rx_wall, rx_monotonic, packet_id, "
    "wheel0_speed, wheel1_speed, wheel0_setpoint, wheel1_setpoint, "
    "imu_accel_x, imu_accel_y, imu_gyro_z, led_state, capture_session";

}  // namespace

int main() {
    std::atomic<bool> stop{false};
    common::install_shutdown_handler(&stop);

    if (common::load_dotenv()) std::println("config: loaded .env");

    const std::string group = common::env_str("ROBOT_MCAST_GROUP", "239.0.0.1");
    const int port = common::env_int("ROBOT_MCAST_PORT", 10001);
    const std::string iface = common::env_str("ROBOT_MCAST_IFACE", "0.0.0.0");
    const std::string conninfo = common::env_str(
        "DB_CONNINFO",
        "host=localhost port=5432 dbname=robot_data user=robot_writer");
    const int batch = common::env_int("DB_BATCH_SIZE", 50);
    const int latency_ms = common::env_int("DB_MAX_LATENCY_MS", 200);

    // One capture_session value per logger run, stamped on every row so each run
    // is self-identifying in the database (no post-hoc attribution guesswork).
    const std::string session_sql = common::sql_timestamp(common::now_rx().wall);
    auto format_row = [session_sql](const Telemetry& t) {
        std::string s = "(";
        s += common::sql_timestamp(t.rx.wall);          s += ',';
        s += common::sql_float(t.rx.monotonic);         s += ',';
        s += common::sql_int(static_cast<long long>(t.packet_id)); s += ',';
        s += common::sql_float(t.wheel0_speed);         s += ',';
        s += common::sql_float(t.wheel1_speed);         s += ',';
        s += common::sql_float(t.wheel0_setpoint);      s += ',';
        s += common::sql_float(t.wheel1_setpoint);      s += ',';
        s += common::sql_float(t.imu_accel_x);          s += ',';
        s += common::sql_float(t.imu_accel_y);          s += ',';
        s += common::sql_float(t.imu_gyro_z);           s += ',';
        s += common::sql_int(t.led_state);              s += ',';
        s += session_sql;                               s += ')';
        return s;
    };

    common::BlockingQueue<Telemetry> queue;
    common::BatchWriter<Telemetry> writer(conninfo, "robot.telemetry", kColumns,
                                          format_row, batch,
                                          std::chrono::milliseconds(latency_ms));
    std::jthread worker([&] { writer.run(queue, stop); });

    std::println("robot_logger: listening on {}:{} -> robot.telemetry "
                 "(capture_session={})", group, port, session_sql);

    int rc = 0;
    try {
        common::UdpReceiver sock(group, static_cast<uint16_t>(port), iface);
        robot::TelemetryParser parser;
        std::vector<Telemetry> recs;
        uint8_t buf[2048];

        uint64_t total = 0, lost = 0;
        bool have_last = false;
        uint32_t last_id = 0;
        auto last_report = std::chrono::steady_clock::now();

        while (!stop.load()) {
            ssize_t n = sock.recv(buf, sizeof(buf));
            if (n <= 0) continue;  // EINTR etc.; re-check stop
            common::RxTime rx = common::now_rx();

            recs.clear();
            parser.feed(rx, std::span{buf, static_cast<std::size_t>(n)}, recs);
            for (const auto& r : recs) {
                if (have_last && r.packet_id > last_id + 1)
                    lost += r.packet_id - (last_id + 1);
                last_id = r.packet_id;
                have_last = true;
                ++total;
                queue.push(r);
            }

            auto now = std::chrono::steady_clock::now();
            if (now - last_report >= std::chrono::seconds(1)) {
                std::println(stderr,
                             "[robot] rx={} lost={} last_id={} queue={}", total,
                             lost, last_id, queue.size());
                last_report = now;
            }
        }
    } catch (const std::exception& e) {
        std::println(stderr, "robot_logger fatal: {}", e.what());
        rc = 1;
    }

    // Clean shutdown: stop the worker and let it flush everything still queued.
    stop.store(true);
    std::println("robot_logger: shutting down, flushing...");
    worker.join();

    // Exit hard, skipping C++ global destructors: libpqxx 7.10 double-frees a
    // static std::string in its shared-library finalizers at exit (confirmed via
    // gdb). All rows are already committed and the worker is joined, so there is
    // nothing left to clean up that the OS won't reclaim.
    std::fflush(nullptr);
    std::quick_exit(rc);
}
