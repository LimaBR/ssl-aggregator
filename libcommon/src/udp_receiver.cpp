#include "common/udp_receiver.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>

namespace common {

namespace {
[[noreturn]] void fail(const std::string& what) {
    throw std::runtime_error(what + ": " + std::strerror(errno));
}
}  // namespace

UdpReceiver::UdpReceiver(const std::string& group, uint16_t port,
                         const std::string& iface) {
    fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) fail("socket");

    // Allow several listeners on the same multicast port (e.g. ssl-vision tools
    // and this logger at once).
    int yes = 1;
    if (::setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) < 0)
        fail("setsockopt SO_REUSEADDR");

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);  // bind any; filtering is by group
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
        fail("bind");

    ip_mreq mreq{};
    if (::inet_pton(AF_INET, group.c_str(), &mreq.imr_multiaddr) != 1)
        throw std::runtime_error("invalid multicast group: " + group);
    if (::inet_pton(AF_INET, iface.c_str(), &mreq.imr_interface) != 1)
        throw std::runtime_error("invalid interface address: " + iface);
    if (::setsockopt(fd_, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq)) < 0)
        fail("setsockopt IP_ADD_MEMBERSHIP");
}

UdpReceiver::~UdpReceiver() {
    if (fd_ >= 0) ::close(fd_);
}

ssize_t UdpReceiver::recv(uint8_t* buf, size_t buflen) {
    return ::recv(fd_, buf, buflen, 0);
}

}  // namespace common
