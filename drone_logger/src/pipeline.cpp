#include "pipeline.hpp"

#include <gst/app/gstappsink.h>
#include <gst/app/gstappsrc.h>
#include <gst/video/video-info.h>

#include <chrono>
#include <print>
#include <stdexcept>

namespace drone {

namespace {

std::pair<int64_t, double> now_pair() {
    using namespace std::chrono;
    const int64_t wall = duration_cast<nanoseconds>(system_clock::now().time_since_epoch()).count();
    const double mono = duration<double>(steady_clock::now().time_since_epoch()).count();
    return {wall, mono};
}

// Raw-video caps for v4l2sink. v4l2loopback (0.12) only accepts YUY2 caps that
// state interlace-mode=progressive and colorimetry 2:4:7:1, and v4l2sink
// refuses the extra fields a decoder adds (multiview-*, other colorimetry) with
// "not-negotiated". The colorimetry is a label only: the pixel values are not
// converted, and SSL-Vision is colour-calibrated on the values it receives.
// Caller owns the result.
GstCaps* plain_video_caps(GstCaps* caps) {
    GstVideoInfo info;
    if (!gst_video_info_from_caps(&info, caps)) return gst_caps_copy(caps);
    // The drone's SPS carries no frame rate (decoded caps say 0/1), and
    // v4l2sink only accepts 1/1..1000/1. Label it with the nominal 30 fps that
    // StreamInfo reports; frames are still passed on as they arrive (sync=false).
    if (GST_VIDEO_INFO_FPS_N(&info) <= 0) {
        GST_VIDEO_INFO_FPS_N(&info) = 30;
        GST_VIDEO_INFO_FPS_D(&info) = 1;
    }
    return gst_caps_new_simple("video/x-raw",
        "format", G_TYPE_STRING, gst_video_format_to_string(GST_VIDEO_INFO_FORMAT(&info)),
        "width", G_TYPE_INT, GST_VIDEO_INFO_WIDTH(&info),
        "height", G_TYPE_INT, GST_VIDEO_INFO_HEIGHT(&info),
        "framerate", GST_TYPE_FRACTION, GST_VIDEO_INFO_FPS_N(&info), GST_VIDEO_INFO_FPS_D(&info),
        "pixel-aspect-ratio", GST_TYPE_FRACTION, GST_VIDEO_INFO_PAR_N(&info), GST_VIDEO_INFO_PAR_D(&info),
        "interlace-mode", G_TYPE_STRING, "progressive",
        "colorimetry", G_TYPE_STRING, "2:4:7:1",
        nullptr);
}

bool has_factory(const std::string& name) {
    GstElementFactory* f = gst_element_factory_find(name.c_str());
    if (!f) return false;
    gst_object_unref(f);
    return true;
}

GstElement* launch(const std::string& desc) {
    GError* err = nullptr;
    GstElement* p = gst_parse_launch(desc.c_str(), &err);
    if (err) {
        std::string msg = err->message;
        g_error_free(err);
        if (p) gst_object_unref(p);
        throw std::runtime_error("gst_parse_launch: " + msg + "\n  pipeline: " + desc);
    }
    return p;
}

// Prints errors and warnings; returns false if an error was seen.
bool drain_bus(GstElement* pipeline, const char* who, bool* eos = nullptr) {
    bool ok = true;
    GstBus* bus = gst_element_get_bus(pipeline);
    while (GstMessage* msg = gst_bus_pop_filtered(
               bus, static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_WARNING | GST_MESSAGE_EOS))) {
        if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_EOS) {
            if (eos) *eos = true;
        } else {
            GError* err = nullptr;
            gchar* dbg = nullptr;
            const bool is_err = GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR;
            if (is_err) gst_message_parse_error(msg, &err, &dbg);
            else gst_message_parse_warning(msg, &err, &dbg);
            std::println(stderr, "[{}] gstreamer {} from {}: {}{}{}", who, is_err ? "ERROR" : "warning",
                         GST_OBJECT_NAME(GST_MESSAGE_SRC(msg)), err ? err->message : "?",
                         dbg ? " | " : "", dbg ? dbg : "");
            if (err) g_error_free(err);
            g_free(dbg);
            if (is_err) ok = false;
        }
        gst_message_unref(msg);
    }
    gst_object_unref(bus);
    return ok;
}

}  // namespace

// ---------------------------------------------------------------- InjectPipeline

InjectPipeline::InjectPipeline(const PipelineConfig& cfg, OnInjected on_injected)
    : cfg_(cfg), on_injected_(std::move(on_injected)) {}

InjectPipeline::~InjectPipeline() {
    std::lock_guard lk(m_);
    teardown();
}

void InjectPipeline::build(GstCaps* caps) {
    std::string desc = "appsrc name=vsrc is-live=true format=time do-timestamp=true ! tee name=vt";
    if (cfg_.inject)
        desc += " vt. ! queue max-size-buffers=2 ! v4l2sink name=v4l2 device=\"" + cfg_.v4l2_device + "\" sync=false";
    if (cfg_.show)
        desc += " vt. ! queue leaky=downstream max-size-buffers=1 ! videoconvert ! autovideosink sync=false";
    pipeline_ = launch(desc);
    src_ = gst_bin_get_by_name(GST_BIN(pipeline_), "vsrc");
    caps_ = plain_video_caps(caps);
    gst_app_src_set_caps(GST_APP_SRC(src_), caps_);

    GstVideoInfo info;
    if (gst_video_info_from_caps(&info, caps)) {
        width_ = GST_VIDEO_INFO_WIDTH(&info);
        height_ = GST_VIDEO_INFO_HEIGHT(&info);
    }
    if (cfg_.inject) {
        GstElement* sink = gst_bin_get_by_name(GST_BIN(pipeline_), "v4l2");
        GstPad* pad = gst_element_get_static_pad(sink, "sink");
        gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &InjectPipeline::on_sink_buffer, this, nullptr);
        gst_object_unref(pad);
        gst_object_unref(sink);
    }
    gst_element_set_state(pipeline_, GST_STATE_PLAYING);
    gchar* caps_str = gst_caps_to_string(caps_);
    std::println("drone_logger: injection pipeline caps {}", caps_str);
    g_free(caps_str);
    std::println("drone_logger: injection pipeline up, {}x{}{}{}", width_, height_,
                 cfg_.inject ? ", v4l2sink " + cfg_.v4l2_device : std::string{},
                 cfg_.show ? ", display" : "");
}

void InjectPipeline::teardown() {
    if (!pipeline_) return;
    gst_element_set_state(pipeline_, GST_STATE_NULL);
    gst_object_unref(src_);
    gst_object_unref(pipeline_);
    gst_caps_unref(caps_);
    pipeline_ = src_ = nullptr;
    caps_ = nullptr;
    std::lock_guard fl(fifo_m_);
    fifo_.clear();
}

void InjectPipeline::push(GstSample* sample, uint32_t rtp_ts, bool rtp_ts_known) {
    std::lock_guard lk(m_);
    GstCaps* caps = gst_sample_get_caps(sample);
    if (!caps) return;
    if (pipeline_) {
        GstCaps* plain = plain_video_caps(caps);
        const bool same = gst_caps_is_equal(plain, caps_);
        gst_caps_unref(plain);
        if (!same) {
            std::println(stderr, "[drone] decoded format changed, rebuilding the injection pipeline");
            teardown();
        }
    }
    if (!pipeline_) {
        // After an error, rebuild at most every 2 s; frames in between are counted.
        if (std::chrono::steady_clock::now() < retry_after_) {
            dropped_.fetch_add(1);
            return;
        }
        build(caps);
    }

    // Shallow copy without timestamps: appsrc stamps its own running time.
    GstBuffer* buf = gst_buffer_copy(gst_sample_get_buffer(sample));
    GST_BUFFER_PTS(buf) = GST_CLOCK_TIME_NONE;
    GST_BUFFER_DTS(buf) = GST_CLOCK_TIME_NONE;
    if (cfg_.inject) {
        std::lock_guard fl(fifo_m_);
        fifo_.emplace_back(rtp_ts, rtp_ts_known);
        if (fifo_.size() > 64) fifo_.pop_front();
    }
    gst_app_src_push_buffer(GST_APP_SRC(src_), buf);
}

GstPadProbeReturn InjectPipeline::on_sink_buffer(GstPad*, GstPadProbeInfo*, gpointer self_) {
    auto* self = static_cast<InjectPipeline*>(self_);
    InjectedFrame f;
    auto [wall, mono] = now_pair();
    f.wall_ns = wall;
    f.mono = mono;
    f.width = self->width_;
    f.height = self->height_;
    {
        std::lock_guard fl(self->fifo_m_);
        if (!self->fifo_.empty()) {
            f.rtp_ts = self->fifo_.front().first;
            f.rtp_ts_known = self->fifo_.front().second;
            self->fifo_.pop_front();
        }
    }
    self->injected_.fetch_add(1);
    if (self->on_injected_) self->on_injected_(f);
    return GST_PAD_PROBE_OK;
}

void InjectPipeline::poll_bus() {
    std::lock_guard lk(m_);
    if (pipeline_ && !drain_bus(pipeline_, "inject")) {
        std::println(stderr, "[drone] injection pipeline error, rebuilding in 2 s");
        teardown();
        retry_after_ = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    }
}

// ---------------------------------------------------------------- StreamPipeline

StreamPipeline::StreamPipeline(const PipelineConfig& cfg, const std::string& mkv_path, InjectPipeline* inject)
    : inject_(inject) {
    decoder_ = cfg.decoder;
    if (!has_factory(decoder_)) {
        std::println(stderr, "[drone] decoder {} not available, using avdec_h264", decoder_);
        decoder_ = "avdec_h264";
    }
    const bool decode = inject_ != nullptr;

    std::string desc =
        "appsrc name=rtpsrc is-live=true format=time do-timestamp=true max-bytes=4000000 "
        "caps=\"application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload=96\" ! "
        "rtpjitterbuffer name=jb latency=" + std::to_string(cfg.jitter_latency_ms) + " drop-on-latency=true ! "
        "rtph264depay ! h264parse config-interval=-1 ! tee name=t";
    if (cfg.record)
        desc += " t. ! queue ! matroskamux ! filesink location=\"" + mkv_path + "\"";
    if (decode)
        desc += " t. ! queue max-size-buffers=4 ! " + decoder_ +
                " ! videoconvert ! video/x-raw,format=YUY2 ! appsink name=dec sync=false emit-signals=true max-buffers=4";
    if (!cfg.record && !decode) desc += " t. ! fakesink";

    pipeline_ = launch(desc);
    src_ = gst_bin_get_by_name(GST_BIN(pipeline_), "rtpsrc");

    GstElement* jb = gst_bin_get_by_name(GST_BIN(pipeline_), "jb");
    GstPad* pad = gst_element_get_static_pad(jb, "src");
    gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &StreamPipeline::on_jitter_out, this, nullptr);
    gst_object_unref(pad);
    gst_object_unref(jb);

    if (decode) {
        GstElement* sink = gst_bin_get_by_name(GST_BIN(pipeline_), "dec");
        g_signal_connect(sink, "new-sample", G_CALLBACK(&StreamPipeline::on_decoded), this);
        gst_object_unref(sink);
    }
    gst_element_set_state(pipeline_, GST_STATE_PLAYING);
}

StreamPipeline::~StreamPipeline() {
    finish(0);
    gst_object_unref(src_);
    gst_object_unref(pipeline_);
}

void StreamPipeline::push_rtp(const uint8_t* data, std::size_t len) {
    GstBuffer* buf = gst_buffer_new_memdup(data, len);
    gst_app_src_push_buffer(GST_APP_SRC(src_), buf);
}

void StreamPipeline::finish(int timeout_ms) {
    if (finished_) return;
    finished_ = true;
    if (timeout_ms > 0) {
        gst_app_src_end_of_stream(GST_APP_SRC(src_));
        GstBus* bus = gst_element_get_bus(pipeline_);
        GstMessage* msg = gst_bus_timed_pop_filtered(
            bus, static_cast<GstClockTime>(timeout_ms) * GST_MSECOND,
            static_cast<GstMessageType>(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
        if (msg) gst_message_unref(msg);
        else std::println(stderr, "[drone] stream pipeline did not reach EOS in {} ms", timeout_ms);
        gst_object_unref(bus);
    }
    gst_element_set_state(pipeline_, GST_STATE_NULL);
}

bool StreamPipeline::poll_bus() { return drain_bus(pipeline_, "stream"); }

GstPadProbeReturn StreamPipeline::on_jitter_out(GstPad*, GstPadProbeInfo* info, gpointer self_) {
    auto* self = static_cast<StreamPipeline*>(self_);
    GstBuffer* buf = GST_PAD_PROBE_INFO_BUFFER(info);
    uint8_t hdr[8];
    if (gst_buffer_extract(buf, 0, hdr, sizeof(hdr)) != sizeof(hdr)) return GST_PAD_PROBE_OK;
    const uint32_t ts = (static_cast<uint32_t>(hdr[4]) << 24) | (static_cast<uint32_t>(hdr[5]) << 16) |
                        (static_cast<uint32_t>(hdr[6]) << 8) | hdr[7];
    const GstClockTime pts = GST_BUFFER_PTS(buf);
    std::lock_guard lk(self->map_m_);
    // Every packet of an access unit has the same RTP timestamp but its own
    // PTS; the depayloader stamps the access unit with one of them, so all are kept.
    auto& m = self->pts_to_rtp_;
    if (m.empty() || m.back().first != pts) {
        m.emplace_back(pts, ts);
        if (m.size() > 4096) m.pop_front();
    }
    return GST_PAD_PROBE_OK;
}

bool StreamPipeline::lookup_rtp_ts(GstClockTime pts, uint32_t* ts) {
    std::lock_guard lk(map_m_);
    for (auto it = pts_to_rtp_.rbegin(); it != pts_to_rtp_.rend(); ++it) {
        if (it->first == pts) {
            *ts = it->second;
            return true;
        }
    }
    return false;
}

GstFlowReturn StreamPipeline::on_decoded(GstElement* sink, gpointer self_) {
    auto* self = static_cast<StreamPipeline*>(self_);
    GstSample* sample = gst_app_sink_pull_sample(GST_APP_SINK(sink));
    if (!sample) return GST_FLOW_OK;
    self->decoded_.fetch_add(1);
    uint32_t ts = 0;
    const bool known = self->lookup_rtp_ts(GST_BUFFER_PTS(gst_sample_get_buffer(sample)), &ts);
    if (self->inject_) self->inject_->push(sample, ts, known);
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

}  // namespace drone
