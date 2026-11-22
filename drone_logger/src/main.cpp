// drone_logger: receives the DJI Mini 3 Pro live video relayed by the phone app
// (RTP/H.264 over UDP, dji-relay docs/protocol.md), records the original
// bitstream, and injects the decoded video into SSL-Vision through a
// v4l2loopback device (spec 8.3, 9.1).
//
// F3 scope: video path only. Per access unit and per injected frame, rows go to
// CSV files in the session folder; the drone.* tables come in F4.

#include <gst/gst.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <format>
#include <memory>
#include <print>
#include <string>

#include "common/config.hpp"
#include "common/signal.hpp"
#include "common/timestamp.hpp"
#include "common/udp_unicast_receiver.hpp"
#include "csv_writer.hpp"
#include "frame_assembler.hpp"
#include "pipeline.hpp"
#include "rtp.hpp"

namespace {

int64_t to_ns(std::chrono::system_clock::time_point tp) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(tp.time_since_epoch()).count();
}

std::string session_folder_name(std::chrono::system_clock::time_point tp) {
    return std::format("{:%Y%m%dT%H%M%SZ}", std::chrono::floor<std::chrono::seconds>(tp));
}

}  // namespace

int main(int argc, char** argv) {
    std::atomic<bool> stop{false};
    common::install_shutdown_handler(&stop);
    gst_init(&argc, &argv);

    if (common::load_dotenv()) std::println("config: loaded .env");
    const int port = common::env_int("DRONE_VIDEO_PORT", 5600);
    const std::string bind_addr = common::env_str("DRONE_BIND_ADDR", "0.0.0.0");
    const std::string out_root = common::env_str("DRONE_OUTPUT_DIR", "drone_sessions");
    const bool packet_log = common::env_int("DRONE_PACKET_LOG", 0) != 0;
    const int stream_timeout_ms = common::env_int("DRONE_STREAM_TIMEOUT_MS", 2000);

    drone::PipelineConfig pcfg;
    pcfg.jitter_latency_ms = common::env_int("DRONE_JITTER_LATENCY_MS", 50);
    pcfg.decoder = common::env_str("DRONE_DECODER", "nvh264dec");
    pcfg.record = common::env_int("DRONE_RECORD", 1) != 0;
    pcfg.inject = common::env_int("DRONE_INJECT", 1) != 0;
    pcfg.v4l2_device = common::env_str("DRONE_V4L2_DEVICE", "/dev/video10");
    pcfg.show = common::env_int("DRONE_SHOW_VIDEO", 0) != 0;

    // One capture_session per logger run (same convention as the other loggers).
    const common::RxTime start = common::now_rx();
    const std::string session_sql = common::sql_timestamp(start.wall);
    const std::filesystem::path dir = std::filesystem::path(out_root) / session_folder_name(start.wall);
    std::filesystem::create_directories(dir);

    std::println("drone_logger: listening on {}:{} (capture_session={})", bind_addr, port, session_sql);
    std::println("drone_logger: output {}, jitter buffer {} ms, decoder {}, record={}, inject={} ({}), display={}",
                 dir.string(), pcfg.jitter_latency_ms, pcfg.decoder, pcfg.record, pcfg.inject,
                 pcfg.v4l2_device, pcfg.show);

    int rc = 0;
    try {
        drone::CsvWriter frames_csv(
            (dir / "live_frames.csv").string(),
            "capture_session,ssrc,segment,frame_idx,rtp_ts,seq_first,seq_last,n_packets,n_lost,complete,key,"
            "size,t_rx_ns,pts_ms,kernel_first_ns,kernel_last_ns,rx_wall_first_ns,rx_mono_first,rx_mono_last");
        drone::CsvWriter inject_csv(
            (dir / "injected_frames.csv").string(),
            "capture_session,stream,rtp_ts,inject_wall_ns,inject_monotonic,width,height");
        std::unique_ptr<drone::CsvWriter> packets_csv;
        if (packet_log)
            packets_csv = std::make_unique<drone::CsvWriter>(
                (dir / "rtp_packets.csv").string(),
                "kernel_ns,rx_mono,ssrc,seq,rtp_ts,marker,size,has_ext");

        const std::string session_csv = std::format("{:%FT%TZ}", std::chrono::floor<std::chrono::microseconds>(start.wall));
        std::atomic<int> stream_index{-1};

        std::unique_ptr<drone::InjectPipeline> inject;
        if (pcfg.inject || pcfg.show) {
            inject = std::make_unique<drone::InjectPipeline>(pcfg, [&](const drone::InjectedFrame& f) {
                inject_csv.push(std::format("{},{},{},{},{:.9f},{},{}", session_csv, stream_index.load(),
                                            f.rtp_ts_known ? std::to_string(f.rtp_ts) : std::string{},
                                            f.wall_ns, f.mono, f.width, f.height));
            });
        }

        drone::FrameAssembler assembler([&](const drone::LiveFrame& f) {
            const auto& e = f.ext;
            frames_csv.push(std::format(
                "{},{:08x},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{:.9f},{:.9f}", session_csv, f.ssrc,
                e ? std::to_string(e->segment) : "", e ? std::to_string(e->frame_idx) : "", f.rtp_ts,
                f.seq_first, f.seq_last, f.n_packets, f.n_lost, f.complete ? 1 : 0, f.key ? 1 : 0, f.size,
                e ? std::to_string(e->t_rx_ns) : "", e ? std::to_string(e->pts_ms) : "", f.kernel_first_ns,
                f.kernel_last_ns, f.wall_first_ns, f.mono_first, f.mono_last));
        });

        std::unique_ptr<drone::StreamPipeline> stream;
        uint32_t stream_ssrc = 0;
        auto end_stream = [&](const char* why) {
            if (!stream) return;
            assembler.flush();
            std::println("drone_logger: stream {} ended ({}), finalising the recording", stream_index.load(), why);
            stream->finish();
            stream.reset();
        };

        common::UdpUnicastReceiver sock(static_cast<uint16_t>(port), bind_addr);
        std::println("drone_logger: socket receive buffer {} bytes", sock.rcvbuf());

        using clock = std::chrono::steady_clock;
        auto last_report = clock::now();
        auto last_packet = clock::now();
        uint64_t bytes = 0, last_bytes = 0, last_packets = 0, last_frames = 0, last_injected = 0;
        uint64_t last_decoded = 0, not_rtp = 0;

        while (!stop.load()) {
            auto batch = sock.recv_batch();
            const common::RxTime rx = common::now_rx();
            const int64_t wall_ns = to_ns(rx.wall);

            for (const auto& d : batch) {
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

            // Stream pause (phone stopped streaming, Wi-Fi gone): finalise the file.
            if (stream && clock::now() - last_packet > std::chrono::milliseconds(stream_timeout_ms))
                end_stream("no packets");
            if (stream && !stream->poll_bus()) end_stream("pipeline error");
            if (inject) inject->poll_bus();

            const auto now = clock::now();
            if (now - last_report >= std::chrono::seconds(1)) {
                const double dt = std::chrono::duration<double>(now - last_report).count();
                const uint64_t pk = assembler.packets(), fr = assembler.frames();
                const uint64_t inj = inject ? inject->injected() : 0;
                const uint64_t dec = stream ? stream->decoded() : 0;
                if (dec < last_decoded) last_decoded = 0;  // new stream pipeline
                std::println(stderr,
                             "[drone] pkt/s={:.0f} Mb/s={:.2f} frames/s={:.1f} decoded/s={:.1f} injected/s={:.1f} "
                             "lost_pkts={} incomplete={} inject_dropped={} ssrc={:08x} segment={} stream={} csv_backlog={}{}",
                             (pk - last_packets) / dt, (bytes - last_bytes) * 8 / dt / 1e6,
                             (fr - last_frames) / dt, (dec - last_decoded) / dt, (inj - last_injected) / dt,
                             assembler.lost_packets(), assembler.incomplete_frames(),
                             inject ? inject->dropped() : 0, assembler.ssrc(),
                             assembler.segment(), stream ? "on" : "idle",
                             frames_csv.backlog() + inject_csv.backlog(),
                             not_rtp ? std::format(" not_rtp={}", not_rtp) : std::string{});
                last_report = now;
                last_packets = pk;
                last_frames = fr;
                last_bytes = bytes;
                last_injected = inj;
                last_decoded = dec;
            }
        }

        std::println("drone_logger: shutting down");
        end_stream("shutdown");
        inject.reset();
        frames_csv.close();
        inject_csv.close();
        if (packets_csv) packets_csv->close();
        std::println("drone_logger: {} access units, {} lost packets, files in {}", assembler.frames(),
                     assembler.lost_packets(), dir.string());
    } catch (const std::exception& e) {
        std::println(stderr, "drone_logger fatal: {}", e.what());
        rc = 1;
    }

    // Same exit as the other loggers: skip global destructors (libpqxx 7.10
    // double free at exit, linked through libcommon).
    std::fflush(nullptr);
    std::quick_exit(rc);
}
