#include "common/timestamp.hpp"

#include <format>

namespace common {

RxTime now_rx() {
    return {
        .wall = std::chrono::system_clock::now(),
        .monotonic = std::chrono::duration<double>(
                         std::chrono::steady_clock::now().time_since_epoch())
                         .count(),
    };
}

std::string sql_timestamp(std::chrono::system_clock::time_point tp) {
    // system_clock formats as UTC; floor to microseconds for Postgres precision.
    auto us = std::chrono::floor<std::chrono::microseconds>(tp);
    return std::format("'{:%F %T}+00'", us);
}

}  // namespace common
