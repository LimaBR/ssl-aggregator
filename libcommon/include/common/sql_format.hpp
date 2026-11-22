#pragma once
#include <cmath>
#include <format>
#include <optional>
#include <string>
#include <string_view>

// Helpers to format machine-generated numeric values as SQL literals for use
// inside generated multi-row INSERTs. These values are produced by us (sensor
// floats, ints, timestamps) -- never user input -- so direct splicing is safe.
namespace common {

// Non-finite floats (NaN/Inf) become NULL rather than risking a bad insert.
// std::format's default float formatting is the shortest round-trippable form.
inline std::string sql_float(double v) {
    if (!std::isfinite(v)) return "NULL";
    return std::format("{}", v);
}

inline std::string sql_float(std::optional<double> v) {
    return v ? sql_float(*v) : std::string("NULL");
}

inline std::string sql_int(long long v) { return std::format("{}", v); }

inline std::string sql_int(std::optional<long long> v) {
    return v ? std::format("{}", *v) : std::string("NULL");
}

inline std::string sql_bool(bool v) { return v ? "TRUE" : "FALSE"; }

// Text literal for values that come from the network (e.g. the drone's JSON
// messages), so unlike the numeric helpers above they are escaped: single
// quotes are doubled and NUL bytes removed. With standard_conforming_strings
// on (the PostgreSQL default), backslashes are literal in '...' strings.
inline std::string sql_text(std::string_view v) {
    std::string s = "'";
    s.reserve(v.size() + 2);
    for (char c : v) {
        if (c == '\0') continue;
        if (c == '\'') s += '\'';
        s += c;
    }
    s += '\'';
    return s;
}

inline std::string sql_text_opt(const std::optional<std::string>& v) {
    return v ? sql_text(*v) : std::string("NULL");
}

}  // namespace common
