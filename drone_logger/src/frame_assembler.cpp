#include "frame_assembler.hpp"

namespace drone {

void FrameAssembler::push(const RtpPacket& p, int64_t kernel_ns, double mono, int64_t wall_ns) {
    ++packets_;

    uint32_t gap = 0;
    if (have_seq_ && p.ssrc == cur_.ssrc) {
        const uint16_t expected = static_cast<uint16_t>(last_seq_ + 1);
        const uint16_t d = static_cast<uint16_t>(p.seq - expected);
        if (d != 0 && d < 0x8000) gap = d;  // forward jump = lost packets
    }
    if (have_seq_ && p.ssrc != cur_.ssrc && open_) close();  // new session
    lost_ += gap;

    if (open_ && (p.timestamp != cur_.rtp_ts || p.ssrc != cur_.ssrc)) close();

    if (!open_) {
        cur_ = LiveFrame{};
        cur_.ssrc = p.ssrc;
        cur_.rtp_ts = p.timestamp;
        cur_.seq_first = p.seq;
        cur_.kernel_first_ns = kernel_ns;
        cur_.mono_first = mono;
        cur_.wall_first_ns = wall_ns;
        marker_ = false;
        open_ = true;
    }
    cur_.n_lost += gap;
    cur_.seq_last = p.seq;
    cur_.n_packets++;
    cur_.size += p.payload_len;
    cur_.kernel_last_ns = kernel_ns;
    cur_.mono_last = mono;
    if (p.ext) {
        cur_.ext = p.ext;
        segment_ = p.ext->segment;
    }
    if (h264_payload_nal_type(p.payload, p.payload_len, nullptr) == 5) cur_.key = true;

    last_seq_ = p.seq;
    have_seq_ = true;
    if (p.marker) {
        marker_ = true;
        close();
    }
}

void FrameAssembler::flush() {
    if (open_) close();
}

void FrameAssembler::close() {
    cur_.complete = marker_ && cur_.ext.has_value() && cur_.n_lost == 0;
    ++frames_;
    if (!cur_.complete) ++incomplete_;
    open_ = false;
    sink_(cur_);
}

}  // namespace drone
