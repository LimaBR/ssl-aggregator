#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
#include <sys/types.h>

namespace common {

// Blocking UDP receiver that joins an IPv4 multicast group.
// Both robot telemetry (239.0.0.1:10001) and SSL-Vision (224.5.23.2:10006)
// are multicast, so this is the single entry point for both loggers.
class UdpReceiver {
public:
    // group : multicast address to join, e.g. "239.0.0.1"
    // port  : UDP port to bind
    // iface : local interface address to join on ("0.0.0.0" = default/any)
    UdpReceiver(const std::string& group, uint16_t port,
                const std::string& iface = "0.0.0.0");
    ~UdpReceiver();

    UdpReceiver(const UdpReceiver&) = delete;
    UdpReceiver& operator=(const UdpReceiver&) = delete;

    // Blocking receive of one datagram. Returns bytes read, or -1 on error
    // (e.g. interrupted by a signal, so callers can re-check their stop flag).
    ssize_t recv(uint8_t* buf, size_t buflen);

    int fd() const { return fd_; }

private:
    int fd_ = -1;
};

}  // namespace common
