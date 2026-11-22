#include "rtp.hpp"

namespace drone {

namespace {
uint16_t be16(const uint8_t* p) { return static_cast<uint16_t>((p[0] << 8) | p[1]); }
uint32_t be32(const uint8_t* p) {
    return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8) | p[3];
}
int64_t be64(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; ++i) v = (v << 8) | p[i];
    return static_cast<int64_t>(v);
}

// RFC 8285 one-byte elements: ID (4 bits) | length-1 (4 bits), then the data.
// ID 0 is padding; ID 15 stops parsing.
FrameExtension parse_one_byte_ext(const uint8_t* p, std::size_t len) {
    FrameExtension ext;
    std::size_t i = 0;
    while (i < len) {
        uint8_t b = p[i];
        if (b == 0) { ++i; continue; }
        int id = b >> 4;
        std::size_t n = (b & 0x0F) + 1;
        if (id == 15 || i + 1 + n > len) break;
        const uint8_t* d = p + i + 1;
        if (id == 1 && n == 8) ext.t_rx_ns = be64(d);
        else if (id == 2 && n == 8) ext.pts_ms = be64(d);
        else if (id == 3 && n == 6) {
            ext.frame_idx = be32(d);
            ext.segment = be16(d + 4);
        }
        i += 1 + n;
    }
    return ext;
}
}  // namespace

std::optional<RtpPacket> parse_rtp(const uint8_t* data, std::size_t len) {
    if (len < 12 || (data[0] >> 6) != 2) return std::nullopt;
    RtpPacket p;
    const bool padding = data[0] & 0x20;
    const bool extension = data[0] & 0x10;
    const std::size_t cc = data[0] & 0x0F;
    p.marker = data[1] & 0x80;
    p.payload_type = data[1] & 0x7F;
    p.seq = be16(data + 2);
    p.timestamp = be32(data + 4);
    p.ssrc = be32(data + 8);

    std::size_t off = 12 + 4 * cc;
    if (off > len) return std::nullopt;
    if (extension) {
        if (off + 4 > len) return std::nullopt;
        const uint16_t profile = be16(data + off);
        const std::size_t words = be16(data + off + 2);
        const std::size_t ext_len = 4 * words;
        if (off + 4 + ext_len > len) return std::nullopt;
        if (profile == 0xBEDE) p.ext = parse_one_byte_ext(data + off + 4, ext_len);
        off += 4 + ext_len;
    }
    std::size_t end = len;
    if (padding) {
        const std::size_t pad = data[len - 1];
        if (pad == 0 || off + pad > len) return std::nullopt;
        end -= pad;
    }
    p.payload = data + off;
    p.payload_len = end - off;
    return p;
}

int h264_payload_nal_type(const uint8_t* payload, std::size_t len, bool* fu_start) {
    if (fu_start) *fu_start = false;
    if (len == 0) return -1;
    const int type = payload[0] & 0x1F;
    if (type == 28 && len >= 2) {  // FU-A
        if (fu_start) *fu_start = payload[1] & 0x80;
        return payload[1] & 0x1F;
    }
    return type;
}

}  // namespace drone
