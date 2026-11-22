#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <variant>

#include "db_rows.hpp"

namespace drone {

// One JSON message from UDP 5601 (dji-relay spec 7.7, 7.8; docs/protocol.md),
// already turned into its table row. std::monostate = unknown type or invalid JSON.
using Message = std::variant<std::monostate, PhoneFrameRow, TelemetryRow, EventRow, BeaconRow>;

struct MessageError {
    std::string what;
};

// Parses one datagram. `rx` carries the receive times; the message's own
// phone_session / seq / t_ph_ns are filled in from the JSON.
// Returns std::monostate and sets *err (if given) when it cannot be used.
Message parse_message(const uint8_t* data, std::size_t len, WallClock::time_point wall, double mono,
                      int64_t kernel_ns, MessageError* err);

}  // namespace drone
