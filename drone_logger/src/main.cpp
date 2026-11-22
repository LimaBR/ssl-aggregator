// drone_logger: receives the DJI Mini 3 Pro live video and messages relayed by
// the dji-relay phone app (dji-relay docs/protocol.md), records the original
// bitstream, injects the decoded video into SSL-Vision through a v4l2loopback
// device (spec 8.3, 9.1), and writes everything to the drone.* tables (8.4).
//
// UDP 5600: RTP/H.264 -> frame assembly (drone.live_frame) + GStreamer pipelines.
// UDP 5601: JSON messages -> drone.phone_frame, telemetry, event, clock_beacon;
//           live format checked against DRONE_EXPECT_* (drone.config_check).

#include <gst/gst.h>
#include <poll.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <format>
#include <memory>
#include <mutex>
#include <print>
#include <string>
#include <thread>
#include <vector>

#include "common/batch_writer.hpp"
#include "common/blocking_queue.hpp"
#include "common/config.hpp"
#include "common/signal.hpp"
#include "common/timestamp.hpp"
#include "common/udp_unicast_receiver.hpp"
#include "config_check.hpp"
#include "csv_writer.hpp"
#include "db_rows.hpp"
#include "frame_assembler.hpp"
#include "messages.hpp"
#include "pipeline.hpp"
#include "rtp.hpp"

namespace {

int64_t to_ns(std::chrono::system_clock::time_point tp) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(tp.time_since_epoch()).count();
}

std::string session_folder_name(std::chrono::system_clock::time_point tp) {
    return std::format("{:%Y%m%dT%H%M%SZ}", std::chrono::floor<std::chrono::seconds>(tp));
}

// One drone.* table: its queue, BatchWriter and worker thread.
template <typename Row>
struct Table {
    common::BlockingQueue<Row> queue;
    common::BatchWriter<Row> writer;
    std::jthread worker;

    Table(const std::string& conninfo, const char* name, const char* columns, const std::string& session_sql,
          int batch, int latency_ms, std::atomic<bool>& stop)
        : writer(conninfo, name, columns,
                 [session_sql](const Row& r) { return drone::format_row(r, session_sql); },
                 static_cast<std::size_t>(batch), std::chrono::milliseconds(latency_ms)),
          worker([this, &stop] { writer.run(queue, stop); }) {}
};

struct Tables {
    Table<drone::LiveFrameRow> live_frame;
    Table<drone::PhoneFrameRow> phone_frame;
    Table<drone::TelemetryRow> telemetry;
    Table<drone::EventRow> event;
    Table<drone::BeaconRow> clock_beacon;
    Table<drone::ConfigCheckRow> config_check;

    Tables(const std::string& c, const std::string& s, int b, int l, std::atomic<bool>& stop)
        : live_frame(c, "drone.live_frame", drone::kLiveFrameColumns, s, b, l, stop),
          phone_frame(c, "drone.phone_frame", drone::kPhoneFrameColumns, s, b, l, stop),
          telemetry(c, "drone.telemetry", drone::kTelemetryColumns, s, b, l, stop),
          event(c, "drone.event", drone::kEventColumns, s, b, l, stop),
          clock_beacon(c, "drone.clock_beacon", drone::kBeaconColumns, s, b, l, stop),
          config_check(c, "drone.config_check", drone::kConfigCheckColumns, s, b, l, stop) {}

    std::size_t backlog() const {
        return live_frame.queue.size() + phone_frame.queue.size() + telemetry.queue.size() +
               event.queue.size() + clock_beacon.queue.size() + config_check.queue.size();
    }
};

}  // namespace

int main(int argc, char** argv) {
    std::atomic<bool> stop{false};
    common::install_shutdown_handler(&stop);
    gst_init(&argc, &argv);

    if (common::load_dotenv()) std::println("config: loaded .env");
    const int port = common::env_int("DRONE_VIDEO_PORT", 5600);
    const int msg_port = common::env_int("DRONE_MSG_PORT", 5601);
    const std::string bind_addr = common::env_str("DRONE_BIND_ADDR", "0.0.0.0");
    const std::string out_root = common::env_str("DRONE_OUTPUT_DIR", "drone_sessions");
    const bool packet_log = common::env_int("DRONE_PACKET_LOG", 0) != 0;
    const bool csv = common::env_int("DRONE_CSV", 0) != 0;
    const bool use_db = common::env_int("DRONE_DB", 1) != 0;
    const int stream_timeout_ms = common::env_int("DRONE_STREAM_TIMEOUT_MS", 2000);
    // A live_frame row waits this long for its injection time before it is written.
    const double inject_wait_s = common::env_int("DRONE_INJECT_WAIT_MS", 1500) / 1000.0;
    const std::string conninfo = common::env_str(
        "DB_CONNINFO", "host=localhost port=5432 dbname=robot_data user=robot_writer");
    const int batch = common::env_int("DB_BATCH_SIZE", 50);
    const int latency_ms = common::env_int("DB_MAX_LATENCY_MS", 200);

    drone::PipelineConfig pcfg;
    pcfg.jitter_latency_ms = common::env_int("DRONE_JITTER_LATENCY_MS", 50);
    pcfg.decoder = common::env_str("DRONE_DECODER", "nvh264dec");
    pcfg.record = common::env_int("DRONE_RECORD", 1) != 0;
    pcfg.inject = common::env_int("DRONE_INJECT", 1) != 0;
    pcfg.v4l2_device = common::env_str("DRONE_V4L2_DEVICE", "/dev/video10");
    pcfg.show = common::env_int("DRONE_SHOW_VIDEO", 0) != 0;

    drone::ConfigChecker checker;
    checker.expect("w", common::env_str("DRONE_EXPECT_WIDTH", ""));
    checker.expect("h", common::env_str("DRONE_EXPECT_HEIGHT", ""));
    checker.expect("fps", common::env_str("DRONE_EXPECT_FPS", ""));
    checker.expect("mime", common::env_str("DRONE_EXPECT_MIME", ""));

    // One capture_session per logger run (same convention as the other loggers).
    const common::RxTime start = common::now_rx();
    const std::string session_sql = common::sql_timestamp(start.wall);
    const std::filesystem::path dir = std::filesystem::path(out_root) / session_folder_name(start.wall);
    std::filesystem::create_directories(dir);

    std::println("drone_logger: video {}:{}, messages {}:{} (capture_session={})", bind_addr, port, bind_addr,
                 msg_port, session_sql);
    std::println("drone_logger: output {}, jitter buffer {} ms, decoder {}, record={}, inject={} ({}), display={}, "
                 "db={}, csv={}, config check={}",
                 dir.string(), pcfg.jitter_latency_ms, pcfg.decoder, pcfg.record, pcfg.inject, pcfg.v4l2_device,
                 pcfg.show, use_db, csv, checker.enabled());

    std::atomic<bool> db_stop{false};
    int rc = 0;
    try {
        std::unique_ptr<Tables> db;
        if (use_db) db = std::make_unique<Tables>(conninfo, session_sql, batch, latency_ms, db_stop);

        std::unique_ptr<drone::CsvWriter> frames_csv, inject_csv, packets_csv;
        if (csv) {
            frames_csv = std::make_unique<drone::CsvWriter>(
                (dir / "live_frames.csv").string(),
                "capture_session,ssrc,segment,frame_idx,rtp_ts,seq_first,seq_last,n_packets,n_lost,complete,key,"
                "size,t_rx_ns,pts_ms,kernel_first_ns,kernel_last_ns,rx_wall_first_ns,rx_mono_first,rx_mono_last,"
                "inject_wall_ns,inject_monotonic");
            inject_csv = std::make_unique<drone::CsvWriter>(
                (dir / "injected_frames.csv").string(),
                "capture_session,stream,rtp_ts,inject_wall_ns,inject_monotonic,width,height");
        }
        if (packet_log)
            packets_csv = std::make_unique<drone::CsvWriter>(
                (dir / "rtp_packets.csv").string(), "kernel_ns,rx_mono,ssrc,seq,rtp_ts,marker,size,has_ext");

        const std::string session_csv =
            std::format("{:%FT%TZ}", std::chrono::floor<std::chrono::microseconds>(start.wall));
        std::atomic<int> stream_index{-1};

        // Injection times arrive on a GStreamer thread; they are merged into the
        // pending live frames by the main loop.
        std::mutex inbox_m;
        std::vector<drone::InjectedFrame> inbox;
        std::unique_ptr<drone::InjectPipeline> inject;
        if (pcfg.inject || pcfg.show) {
            inject = std::make_unique<drone::InjectPipeline>(pcfg, [&](const drone::InjectedFrame& f) {
                if (inject_csv)
                    inject_csv->push(std::format("{},{},{},{},{:.9f},{},{}", session_csv, stream_index.load(),
                                                 f.rtp_ts_known ? std::to_string(f.rtp_ts) : std::string{},
                                                 f.wall_ns, f.mono, f.width, f.height));
                if (!f.rtp_ts_known) return;
                std::lock_guard lk(inbox_m);
                inbox.push_back(f);
            });
        }

        // Access units wait in `pending` (in arrival order) for their injection time.
        std::deque<drone::LiveFrameRow> pending;
        uint64_t inject_unmatched = 0;
        auto write_live = [&](const drone::LiveFrameRow& r) {
            if (db) db->live_frame.queue.push(r);
            if (frames_csv) {
                const auto& f = r.f;
                const auto& e = f.ext;
                frames_csv->push(std::format(
                    "{},{:08x},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{:.9f},{:.9f},{},{}", session_csv, f.ssrc,
                    e ? std::to_string(e->segment) : "", e ? std::to_string(e->frame_idx) : "", f.rtp_ts,
                    f.seq_first, f.seq_last, f.n_packets, f.n_lost, f.complete ? 1 : 0, f.key ? 1 : 0, f.size,
                    e ? std::to_string(e->t_rx_ns) : "", e ? std::to_string(e->pts_ms) : "", f.kernel_first_ns,
                    f.kernel_last_ns, f.wall_first_ns, f.mono_first, f.mono_last,
                    r.inject_wall ? std::to_string(to_ns(*r.inject_wall)) : "",
                    r.inject_mono ? std::format("{:.9f}", *r.inject_mono) : ""));
            }
        };
        drone::FrameAssembler assembler([&](const drone::LiveFrame& f) { pending.push_back({f, {}, {}}); });

        std::unique_ptr<drone::StreamPipeline> stream;
        uint32_t stream_ssrc = 0;
        auto end_stream = [&](const char* why) {
            if (!stream) return;
            assembler.flush();
            std::println("drone_logger: stream {} ended ({}), finalising the recording", stream_index.load(), why);
            stream->finish();
            stream.reset();
        };

        common::UdpUnicastReceiver vsock(static_cast<uint16_t>(port), bind_addr);
        common::UdpUnicastReceiver msock(static_cast<uint16_t>(msg_port), bind_addr, 64, 65536, 1 << 20);
        std::println("drone_logger: receive buffers video {} / messages {} bytes", vsock.rcvbuf(), msock.rcvbuf());

        using clock = std::chrono::steady_clock;
        auto last_report = clock::now();
        auto last_packet = clock::now();
        uint64_t bytes = 0, last_bytes = 0, last_packets = 0, last_frames = 0, last_injected = 0;
        uint64_t last_decoded = 0, not_rtp = 0;
        // Message counters.
        uint64_t n_msgs = 0, n_bad = 0, n_beacons = 0, n_telemetry = 0, n_events = 0, n_phone_frames = 0;
        uint64_t last_msgs = 0, last_beacons = 0, last_telemetry = 0;
        long long beacon_last_seq = -1;
        uint64_t beacon_gaps = 0;
        // Clock: d = kernel receive time - t_ph_ns; minimum per 10 s window (spec 7.8).
        std::optional<long long> d_min_window, d_min_first, d_min_last;
        auto window_start = clock::now();

        pollfd fds[2] = {{vsock.fd(), POLLIN, 0}, {msock.fd(), POLLIN, 0}};

        while (!stop.load()) {
            fds[0].revents = fds[1].revents = 0;
            const int pr = ::poll(fds, 2, 200);
            const common::RxTime rx = common::now_rx();
            const int64_t wall_ns = to_ns(rx.wall);

            if (pr > 0 && (fds[0].revents & POLLIN)) {
                for (const auto& d : vsock.recv_batch()) {
                    auto p = drone::parse_rtp(d.data, d.len);
                    if (!p || p->payload_type != 96) {
                        ++not_rtp;
                        continue;
                    }
                    last_packet = clock::now();
                    bytes += d.len;

                    // A new SSRC is a new streaming session on the phone: new recording file.
                    if (stream && p->ssrc != stream_ssrc) end_stream("new SSRC");
                    if (!stream) {
                        const int idx = stream_index.fetch_add(1) + 1;
                        const auto mkv = dir / std::format("video_live_{:02}.mkv", idx);
                        stream = std::make_unique<drone::StreamPipeline>(pcfg, mkv.string(), inject.get());
                        stream_ssrc = p->ssrc;
                        std::println("drone_logger: stream {} started, ssrc {:08x}, decoder {}{}", idx, p->ssrc,
                                     stream->decoder(), pcfg.record ? ", recording " + mkv.string() : std::string{});
                    }

                    assembler.push(*p, d.kernel_ns, rx.monotonic, wall_ns);
                    stream->push_rtp(d.data, d.len);
                    if (packets_csv)
                        packets_csv->push(std::format("{},{:.9f},{:08x},{},{},{},{},{}", d.kernel_ns, rx.monotonic,
                                                      p->ssrc, p->seq, p->timestamp, p->marker ? 1 : 0, d.len,
                                                      p->ext ? 1 : 0));
                }
            }

            if (pr > 0 && (fds[1].revents & POLLIN)) {
                for (const auto& d : msock.recv_batch()) {
                    ++n_msgs;
                    drone::MessageError err;
                    drone::Message m = drone::parse_message(d.data, d.len, rx.wall, rx.monotonic, d.kernel_ns, &err);
                    if (std::holds_alternative<std::monostate>(m)) {
                        if (n_bad++ < 5) std::println(stderr, "[drone] message ignored: {}", err.what);
                        continue;
                    }
                    if (auto* b = std::get_if<drone::BeaconRow>(&m)) {
                        ++n_beacons;
                        if (b->rx.seq) {
                            if (beacon_last_seq >= 0 && *b->rx.seq > beacon_last_seq + 1)
                                beacon_gaps += *b->rx.seq - beacon_last_seq - 1;
                            beacon_last_seq = *b->rx.seq;
                        }
                        if (b->rx.t_ph_ns && b->rx_kernel_ns) {
                            const long long dd = b->rx_kernel_ns - *b->rx.t_ph_ns;
                            if (!d_min_window || dd < *d_min_window) d_min_window = dd;
                        }
                        if (db) db->clock_beacon.queue.push(*b);
                    } else if (auto* t = std::get_if<drone::TelemetryRow>(&m)) {
                        ++n_telemetry;
                        if (db) db->telemetry.queue.push(*t);
                    } else if (auto* e = std::get_if<drone::EventRow>(&m)) {
                        ++n_events;
                        if (e->type != "key_rates")
                            std::println("drone_logger: phone event {}", e->type);
                        if (db) db->event.queue.push(*e);
                    } else if (auto* f = std::get_if<drone::PhoneFrameRow>(&m)) {
                        ++n_phone_frames;
                        // Configuration check on the live format (present on keyframes and on change).
                        auto check = [&](const char* field, const std::optional<std::string>& v) {
                            if (!v) return;
                            if (auto row = checker.report(field, *v, rx.wall, rx.monotonic); row && db)
                                db->config_check.queue.push(*row);
                        };
                        auto num = [](const std::optional<long long>& v) {
                            return v ? std::optional<std::string>(std::to_string(*v)) : std::nullopt;
                        };
                        check("w", num(f->w));
                        check("h", num(f->h));
                        check("fps", num(f->fps));
                        check("mime", f->mime);
                        if (db) db->phone_frame.queue.push(*f);
                    }
                }
            }

            // Merge injection times into the pending access units.
            {
                std::vector<drone::InjectedFrame> got;
                {
                    std::lock_guard lk(inbox_m);
                    got.swap(inbox);
                }
                for (const auto& inj : got) {
                    bool matched = false;
                    for (auto it = pending.rbegin(); it != pending.rend(); ++it) {
                        if (it->f.rtp_ts == inj.rtp_ts && !it->inject_wall) {
                            it->inject_wall = drone::wall_from_ns(inj.wall_ns);
                            it->inject_mono = inj.mono;
                            matched = true;
                            break;
                        }
                    }
                    if (!matched) ++inject_unmatched;
                }
            }
            // Write the access units that waited long enough (or all of them when stopping).
            while (!pending.empty() && pending.front().f.mono_first < rx.monotonic - inject_wait_s) {
                write_live(pending.front());
                pending.pop_front();
            }

            // Stream pause (phone stopped streaming, Wi-Fi gone): finalise the file.
            if (stream && clock::now() - last_packet > std::chrono::milliseconds(stream_timeout_ms))
                end_stream("no packets");
            if (stream && !stream->poll_bus()) end_stream("pipeline error");
            if (inject) inject->poll_bus();

            const auto now = clock::now();
            if (now - window_start >= std::chrono::seconds(10)) {
                if (d_min_window) {
                    if (!d_min_first) d_min_first = d_min_window;
                    d_min_last = d_min_window;
                }
                d_min_window.reset();
                window_start = now;
            }
            if (now - last_report >= std::chrono::seconds(1)) {
                const double dt = std::chrono::duration<double>(now - last_report).count();
                const uint64_t pk = assembler.packets(), fr = assembler.frames();
                const uint64_t inj = inject ? inject->injected() : 0;
                const uint64_t dec = stream ? stream->decoded() : 0;
                if (dec < last_decoded) last_decoded = 0;  // new stream pipeline
                const std::string clock_drift =
                    (d_min_first && d_min_last) ? std::format("{:+.2f}ms", (*d_min_last - *d_min_first) / 1e6) : "-";
                std::println(stderr,
                             "[drone] pkt/s={:.0f} Mb/s={:.2f} frames/s={:.1f} decoded/s={:.1f} injected/s={:.1f} "
                             "lost_pkts={} incomplete={} inject_dropped={} ssrc={:08x} segment={} stream={} | "
                             "msg/s={:.0f} beacons/s={:.1f} beacon_gaps={} telem/s={:.0f} events={} phone_frames={} "
                             "bad_msgs={} clock_dmin_drift={} mismatches={} | db_backlog={}{}",
                             (pk - last_packets) / dt, (bytes - last_bytes) * 8 / dt / 1e6, (fr - last_frames) / dt,
                             (dec - last_decoded) / dt, (inj - last_injected) / dt, assembler.lost_packets(),
                             assembler.incomplete_frames(), inject ? inject->dropped() : 0, assembler.ssrc(),
                             assembler.segment(), stream ? "on" : "idle", (n_msgs - last_msgs) / dt,
                             (n_beacons - last_beacons) / dt, beacon_gaps, (n_telemetry - last_telemetry) / dt,
                             n_events, n_phone_frames, n_bad, clock_drift, checker.mismatches(),
                             db ? db->backlog() : 0, not_rtp ? std::format(" not_rtp={}", not_rtp) : std::string{});
                last_report = now;
                last_packets = pk;
                last_frames = fr;
                last_bytes = bytes;
                last_injected = inj;
                last_decoded = dec;
                last_msgs = n_msgs;
                last_beacons = n_beacons;
                last_telemetry = n_telemetry;
            }
        }

        std::println("drone_logger: shutting down");
        end_stream("shutdown");
        inject.reset();
        while (!pending.empty()) {
            write_live(pending.front());
            pending.pop_front();
        }
        // Stop the DB workers; each flushes what is still queued.
        db_stop.store(true);
        db.reset();
        if (frames_csv) frames_csv->close();
        if (inject_csv) inject_csv->close();
        if (packets_csv) packets_csv->close();
        std::println("drone_logger: {} access units, {} lost packets, {} messages ({} beacons, {} telemetry, "
                     "{} events, {} phone frames), {} injections without a pending frame, files in {}",
                     assembler.frames(), assembler.lost_packets(), n_msgs, n_beacons, n_telemetry, n_events,
                     n_phone_frames, inject_unmatched, dir.string());
    } catch (const std::exception& e) {
        std::println(stderr, "drone_logger fatal: {}", e.what());
        rc = 1;
    }

    // Same exit as the other loggers: skip global destructors (libpqxx 7.10
    // double free at exit).
    std::fflush(nullptr);
    std::quick_exit(rc);
}
