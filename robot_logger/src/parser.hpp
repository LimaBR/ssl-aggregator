#pragma once
#include <cstdint>
#include <span>
#include <string>
#include <vector>

#include "common/timestamp.hpp"

namespace robot {

// One decoded telemetry packet.
// Wire format (ASCII): >Speed:<packet_id>,<f0>,<f1>,<f2>,<f3>,<f4>,<f5>,<f6>,<led>
struct Telemetry {
    common::RxTime rx;
    uint32_t packet_id = 0;
    float wheel0_speed = 0;      // f0: mm/s, encoder
    float wheel1_speed = 0;      // f1: mm/s, encoder
    float wheel0_setpoint = 0;   // f2: mm/s, commanded
    float wheel1_setpoint = 0;   // f3: mm/s, commanded
    float imu_accel_x = 0;       // f4
    float imu_accel_y = 0;       // f5
    float imu_gyro_z = 0;        // f6
    int led_state = 0;           // f7: 0/1
};

// Resynchronising stream parser. The ESP8266 forwards raw UART bytes with no
// message terminator, so a datagram may carry one message (common), several
// (coalesced), or a partial one (split across datagrams). The parser keeps an
// internal buffer, frames messages on the ">Speed:" sentinel, and emits only
// structurally-complete records.
class TelemetryParser {
public:
    // Append bytes received in one datagram (stamped with rx) and append any
    // newly-completed records to `out`.
    void feed(const common::RxTime& rx, std::span<const std::uint8_t> data,
              std::vector<Telemetry>& out);

private:
    // Parse a single "[>Speed:...]" region. Returns true only if the record is
    // structurally complete (packet_id + 7 fixed-width floats + led).
    static bool parse_record(const std::string& region,
                             const common::RxTime& rx, Telemetry& out);

    std::string buf_;
};

}  // namespace robot
