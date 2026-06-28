#include "parser.hpp"

#include <cstdlib>

namespace robot {

namespace {
const std::string kMark = ">Speed:";
constexpr std::size_t kMaxBuf = 4096;  // guard against unbounded growth

// %+0.6e floats are 13 chars ("+1.234560e+02"); allow a little slack for
// 3-digit exponents while still rejecting truncated tokens.
bool looks_like_float(const std::string& tok) {
    return tok.size() >= 12 && tok.size() <= 14;
}

std::vector<std::string> split(const std::string& s, char d) {
    std::vector<std::string> out;
    std::size_t start = 0;
    while (true) {
        std::size_t p = s.find(d, start);
        if (p == std::string::npos) {
            out.push_back(s.substr(start));
            break;
        }
        out.push_back(s.substr(start, p - start));
        start = p + 1;
    }
    return out;
}
}  // namespace

bool TelemetryParser::parse_record(const std::string& region,
                                   const common::RxTime& rx, Telemetry& out) {
    if (region.compare(0, kMark.size(), kMark) != 0) return false;
    std::string body = region.substr(kMark.size());

    std::vector<std::string> tok = split(body, ',');
    if (tok.size() < 9) return false;                 // not all fields yet
    for (int k = 1; k <= 7; ++k)
        if (!looks_like_float(tok[k])) return false;  // truncated float -> wait
    if (tok[8].empty()) return false;

    out.rx = rx;
    out.packet_id     = static_cast<uint32_t>(std::strtoul(tok[0].c_str(), nullptr, 10));
    out.wheel0_speed    = std::strtof(tok[1].c_str(), nullptr);
    out.wheel1_speed    = std::strtof(tok[2].c_str(), nullptr);
    out.wheel0_setpoint = std::strtof(tok[3].c_str(), nullptr);
    out.wheel1_setpoint = std::strtof(tok[4].c_str(), nullptr);
    out.imu_accel_x     = std::strtof(tok[5].c_str(), nullptr);
    out.imu_accel_y     = std::strtof(tok[6].c_str(), nullptr);
    out.imu_gyro_z      = std::strtof(tok[7].c_str(), nullptr);
    out.led_state       = std::atoi(tok[8].c_str());
    return true;
}

void TelemetryParser::feed(const common::RxTime& rx,
                           std::span<const std::uint8_t> data,
                           std::vector<Telemetry>& out) {
    buf_.append(reinterpret_cast<const char*>(data.data()), data.size());

    while (true) {
        std::size_t i = buf_.find(kMark);
        if (i == std::string::npos) {
            // No sentinel. Keep only a small tail in case it straddles the
            // next datagram boundary.
            if (buf_.size() >= kMark.size())
                buf_.erase(0, buf_.size() - (kMark.size() - 1));
            break;
        }
        if (i > 0) buf_.erase(0, i);  // drop leading garbage

        std::size_t j = buf_.find(kMark, kMark.size());
        bool is_last = (j == std::string::npos);
        std::string region = is_last ? buf_ : buf_.substr(0, j);

        Telemetry t;
        if (parse_record(region, rx, t)) {
            out.push_back(t);
            if (is_last) { buf_.clear(); break; }
            buf_.erase(0, j);                 // advance to next message
        } else if (is_last) {
            // Incomplete trailing message: keep it for the next datagram.
            if (buf_.size() > kMaxBuf) buf_.clear();
            break;
        } else {
            // A fully-delimited region that won't parse is corrupt; skip it.
            buf_.erase(0, j);
        }
    }
}

}  // namespace robot
