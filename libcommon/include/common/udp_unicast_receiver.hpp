#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace common {

// One received datagram: its bytes and the kernel receive time
// (SO_TIMESTAMPNS, CLOCK_REALTIME, nanoseconds since the epoch; 0 if absent).
struct Datagram {
    const uint8_t* data = nullptr;
    std::size_t len = 0;
    int64_t kernel_ns = 0;
};

// UDP receiver bound to a unicast port (the drone video and messages arrive by
// unicast; UdpReceiver only joins multicast groups). Receives in batches with
// recvmmsg and reports the kernel receive time of every datagram.
//
// recv_batch() returns after at most `timeout_ms` even with no data, so the
// caller can re-check its stop flag (the shutdown handler does not interrupt
// a blocking receive).
class UdpUnicastReceiver {
public:
    // port      : UDP port to bind
    // iface     : local address to bind ("0.0.0.0" = all interfaces)
    // batch     : datagrams per recvmmsg call
    // max_size  : largest datagram accepted (bytes)
    // rcvbuf    : requested SO_RCVBUF (bytes; the kernel may cap it)
    UdpUnicastReceiver(uint16_t port, const std::string& iface = "0.0.0.0",
                       std::size_t batch = 64, std::size_t max_size = 2048,
                       int rcvbuf = 4 * 1024 * 1024, int timeout_ms = 200);
    ~UdpUnicastReceiver();

    UdpUnicastReceiver(const UdpUnicastReceiver&) = delete;
    UdpUnicastReceiver& operator=(const UdpUnicastReceiver&) = delete;

    // Receives up to `batch` datagrams. The returned views stay valid until the
    // next call. Empty on timeout or interruption.
    std::span<const Datagram> recv_batch();

    int fd() const { return fd_; }
    // Receive buffer size actually granted by the kernel.
    int rcvbuf() const { return rcvbuf_; }

private:
    int fd_ = -1;
    int rcvbuf_ = 0;
    std::size_t batch_;
    std::size_t max_size_;
    std::vector<uint8_t> storage_;
    std::vector<uint8_t> control_;
    std::vector<Datagram> out_;
    struct Impl;
    Impl* impl_ = nullptr;
};

}  // namespace common
