#pragma once
#include <cstddef>
#include <cstdint>
#include <optional>

namespace drone {

// Header extension written by the phone on the first packet of each access
// unit (dji-relay docs/protocol.md: RFC 8285 one-byte form, IDs 1-3).
struct FrameExtension {
    int64_t t_rx_ns = 0;     // phone receive time, elapsedRealtimeNanos
    int64_t pts_ms = 0;      // raw presentationTimeMs (UTC epoch ms)
    uint32_t frame_idx = 0;  // callback index since the app started
    uint16_t segment = 0;    // +1 each time the drone stream is re-attached
};

struct RtpPacket {
    bool marker = false;
    uint8_t payload_type = 0;
    uint16_t seq = 0;
    uint32_t timestamp = 0;
    uint32_t ssrc = 0;
    std::optional<FrameExtension> ext;
    const uint8_t* payload = nullptr;
    std::size_t payload_len = 0;
};

// Parses an RTP packet (RFC 3550). Returns nullopt if it is not a valid
// version-2 RTP packet. The payload points into `data`.
std::optional<RtpPacket> parse_rtp(const uint8_t* data, std::size_t len);

// H.264 NAL type carried by an RFC 6184 payload: the NAL type of a single NAL
// unit packet, or the fragment's original type for FU-A (with *fu_start set to
// the S bit). Returns -1 for an empty payload.
int h264_payload_nal_type(const uint8_t* payload, std::size_t len, bool* fu_start);

}  // namespace drone
