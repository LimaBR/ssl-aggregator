#pragma once
#include <cstdint>
#include <functional>
#include <optional>

#include "rtp.hpp"

namespace drone {

// One access unit as received (spec 8.3 "frame assembly"): one row of
// live_frames.csv now, of drone.live_frame in F4.
struct LiveFrame {
    uint32_t ssrc = 0;
    uint32_t rtp_ts = 0;
    uint16_t seq_first = 0;
    uint16_t seq_last = 0;
    uint32_t n_packets = 0;
    uint32_t n_lost = 0;       // sequence gaps inside or just before this access unit
    bool complete = false;     // marker seen, extension seen, no loss
    bool key = false;          // contains an IDR (type 5)
    uint64_t size = 0;         // RTP payload bytes
    std::optional<FrameExtension> ext;
    int64_t kernel_first_ns = 0;   // kernel receive time, first and last packet
    int64_t kernel_last_ns = 0;
    double mono_first = 0;         // steady clock (now_rx), first and last packet
    double mono_last = 0;
    int64_t wall_first_ns = 0;     // system clock (now_rx), first packet
};

// Groups RTP packets into access units by timestamp, closing a unit at the
// marker bit or when a packet with another timestamp (or SSRC) arrives.
// Packets are expected in arrival order; reordering shows up as loss here
// (the GStreamer jitter buffer still reorders for decoding).
class FrameAssembler {
public:
    using Sink = std::function<void(const LiveFrame&)>;
    explicit FrameAssembler(Sink sink) : sink_(std::move(sink)) {}

    void push(const RtpPacket& p, int64_t kernel_ns, double mono, int64_t wall_ns);
    // Emits the access unit in progress, if any (stream pause, shutdown).
    void flush();

    uint64_t packets() const { return packets_; }
    uint64_t lost_packets() const { return lost_; }
    uint64_t frames() const { return frames_; }
    uint64_t incomplete_frames() const { return incomplete_; }
    uint32_t ssrc() const { return have_seq_ ? cur_.ssrc : 0; }
    uint16_t segment() const { return segment_; }

private:
    void close();

    Sink sink_;
    LiveFrame cur_;
    bool open_ = false;
    bool have_seq_ = false;
    bool marker_ = false;
    uint16_t last_seq_ = 0;
    uint16_t segment_ = 0;
    uint64_t packets_ = 0, lost_ = 0, frames_ = 0, incomplete_ = 0;
};

}  // namespace drone
