#pragma once
#include <chrono>
#include <string>

namespace common {

struct RxTime {
    std::chrono::system_clock::time_point wall;  // wall clock (for TIMESTAMPTZ)
    double monotonic;                             // steady clock, seconds
};

// Capture both clocks as close together as possible, at packet arrival.
RxTime now_rx();

// Format a wall-clock time as a Postgres timestamp literal *including* quotes
// and UTC offset, e.g.  '2026-06-28 13:45:01.123456+00'
// Safe to splice directly into generated SQL.
std::string sql_timestamp(std::chrono::system_clock::time_point tp);

}  // namespace common
