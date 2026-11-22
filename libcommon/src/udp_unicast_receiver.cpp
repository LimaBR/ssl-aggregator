#include "common/udp_unicast_receiver.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <ctime>
#include <stdexcept>

namespace common {

namespace {
[[noreturn]] void fail(const std::string& what) {
    throw std::runtime_error(what + ": " + std::strerror(errno));
}
constexpr std::size_t kControlSize = CMSG_SPACE(sizeof(timespec));
}  // namespace

struct UdpUnicastReceiver::Impl {
    std::vector<mmsghdr> msgs;
    std::vector<iovec> iovs;
};

UdpUnicastReceiver::UdpUnicastReceiver(uint16_t port, const std::string& iface,
                                       std::size_t batch, std::size_t max_size,
                                       int rcvbuf, int timeout_ms)
    : batch_(batch), max_size_(max_size) {
    fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) fail("socket");

    if (::setsockopt(fd_, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf)) < 0)
        fail("setsockopt SO_RCVBUF");
    socklen_t optlen = sizeof(rcvbuf_);
    ::getsockopt(fd_, SOL_SOCKET, SO_RCVBUF, &rcvbuf_, &optlen);

    int yes = 1;
    if (::setsockopt(fd_, SOL_SOCKET, SO_TIMESTAMPNS, &yes, sizeof(yes)) < 0)
        fail("setsockopt SO_TIMESTAMPNS");

    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    if (::setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0)
        fail("setsockopt SO_RCVTIMEO");

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (::inet_pton(AF_INET, iface.c_str(), &addr.sin_addr) != 1)
        throw std::runtime_error("invalid interface address: " + iface);
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
        fail("bind");

    storage_.resize(batch_ * max_size_);
    control_.resize(batch_ * kControlSize);
    out_.resize(batch_);
    impl_ = new Impl;
    impl_->msgs.resize(batch_);
    impl_->iovs.resize(batch_);
}

UdpUnicastReceiver::~UdpUnicastReceiver() {
    if (fd_ >= 0) ::close(fd_);
    delete impl_;
}

std::span<const Datagram> UdpUnicastReceiver::recv_batch() {
    auto& msgs = impl_->msgs;
    auto& iovs = impl_->iovs;
    for (std::size_t i = 0; i < batch_; ++i) {
        iovs[i].iov_base = storage_.data() + i * max_size_;
        iovs[i].iov_len = max_size_;
        msgs[i] = {};
        msgs[i].msg_hdr.msg_iov = &iovs[i];
        msgs[i].msg_hdr.msg_iovlen = 1;
        msgs[i].msg_hdr.msg_control = control_.data() + i * kControlSize;
        msgs[i].msg_hdr.msg_controllen = kControlSize;
    }

    // MSG_WAITFORONE: block (up to SO_RCVTIMEO) for the first datagram, then
    // take whatever else is already queued without waiting.
    int n = ::recvmmsg(fd_, msgs.data(), static_cast<unsigned>(batch_), MSG_WAITFORONE, nullptr);
    if (n <= 0) return {};

    for (int i = 0; i < n; ++i) {
        Datagram& d = out_[i];
        d.data = storage_.data() + static_cast<std::size_t>(i) * max_size_;
        d.len = msgs[i].msg_len;
        d.kernel_ns = 0;
        for (cmsghdr* c = CMSG_FIRSTHDR(&msgs[i].msg_hdr); c != nullptr;
             c = CMSG_NXTHDR(&msgs[i].msg_hdr, c)) {
            if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_TIMESTAMPNS) {
                timespec ts{};
                std::memcpy(&ts, CMSG_DATA(c), sizeof(ts));
                d.kernel_ns = static_cast<int64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
            }
        }
    }
    return {out_.data(), static_cast<std::size_t>(n)};
}

}  // namespace common
