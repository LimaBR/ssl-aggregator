#pragma once
#include <gst/gst.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <utility>

namespace drone {

struct PipelineConfig {
    int jitter_latency_ms = 50;      // DRONE_JITTER_LATENCY_MS
    std::string decoder = "nvh264dec";  // DRONE_DECODER (falls back to avdec_h264)
    bool record = true;              // DRONE_RECORD: video_live_NN.mkv
    bool inject = true;              // DRONE_INJECT: v4l2sink into SSL-Vision
    std::string v4l2_device = "/dev/video10";  // DRONE_V4L2_DEVICE
    bool show = false;               // DRONE_SHOW_VIDEO: display window
};

// One injected frame: the RTP timestamp it came from and when it was handed to
// v4l2sink (spec 8.3: "a pad probe before the sink stamps each frame's
// injection time and its RTP timestamp").
struct InjectedFrame {
    uint32_t rtp_ts = 0;
    bool rtp_ts_known = false;
    int64_t wall_ns = 0;
    double mono = 0;
    int width = 0;
    int height = 0;
};

// Persistent pipeline: appsrc (decoded YUY2) -> tee -> v4l2sink [+ display].
// Built on the first decoded frame and kept for the whole run, so the
// v4l2loopback device stays open across stream interruptions and SSL-Vision
// only waits while no frames arrive. Rebuilt only if the resolution changes.
class InjectPipeline {
public:
    using OnInjected = std::function<void(const InjectedFrame&)>;
    InjectPipeline(const PipelineConfig& cfg, OnInjected on_injected);
    ~InjectPipeline();

    // Hands one decoded frame to the sinks. Called from the stream pipeline's
    // appsink thread.
    void push(GstSample* sample, uint32_t rtp_ts, bool rtp_ts_known);
    void poll_bus();
    uint64_t injected() const { return injected_.load(); }
    // Decoded frames not injected because the pipeline was waiting to be rebuilt.
    uint64_t dropped() const { return dropped_.load(); }
    bool active() const { return pipeline_ != nullptr; }

private:
    void build(GstCaps* caps);
    void teardown();
    static GstPadProbeReturn on_sink_buffer(GstPad*, GstPadProbeInfo*, gpointer self);

    PipelineConfig cfg_;
    OnInjected on_injected_;
    std::mutex m_;
    GstElement* pipeline_ = nullptr;
    GstElement* src_ = nullptr;
    GstCaps* caps_ = nullptr;
    int width_ = 0, height_ = 0;
    std::mutex fifo_m_;
    std::deque<std::pair<uint32_t, bool>> fifo_;  // rtp_ts of frames on their way to v4l2sink
    std::atomic<uint64_t> injected_{0};
    std::atomic<uint64_t> dropped_{0};
    std::chrono::steady_clock::time_point retry_after_{};
};

// Stream pipeline, one per stream (rebuilt for a new SSRC or after a pause):
// appsrc (RTP) -> rtpjitterbuffer -> rtph264depay -> h264parse -> tee ->
//   [matroskamux -> video_live_NN.mkv] + [decoder -> YUY2 -> appsink -> InjectPipeline]
class StreamPipeline {
public:
    StreamPipeline(const PipelineConfig& cfg, const std::string& mkv_path, InjectPipeline* inject);
    ~StreamPipeline();

    // Pushes one RTP packet (copied).
    void push_rtp(const uint8_t* data, std::size_t len);
    // Sends EOS and waits (up to timeout_ms) so the .mkv is finalised.
    void finish(int timeout_ms = 3000);
    // Returns false after an error on the bus (the caller rebuilds the pipeline).
    bool poll_bus();
    uint64_t decoded() const { return decoded_.load(); }
    const std::string& decoder() const { return decoder_; }

private:
    static GstPadProbeReturn on_jitter_out(GstPad*, GstPadProbeInfo*, gpointer self);
    static GstFlowReturn on_decoded(GstElement* sink, gpointer self);
    bool lookup_rtp_ts(GstClockTime pts, uint32_t* ts);

    GstElement* pipeline_ = nullptr;
    GstElement* src_ = nullptr;
    InjectPipeline* inject_ = nullptr;
    std::string decoder_;
    std::mutex map_m_;
    std::deque<std::pair<GstClockTime, uint32_t>> pts_to_rtp_;  // jitterbuffer output
    std::atomic<uint64_t> decoded_{0};
    bool finished_ = false;
};

}  // namespace drone
