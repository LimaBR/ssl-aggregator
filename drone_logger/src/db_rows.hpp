#pragma once
#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "common/sql_format.hpp"
#include "common/timestamp.hpp"
#include "frame_assembler.hpp"

namespace drone {

// Rows of the drone.* tables (sql/04_drone.sql), and their VALUES tuples for
// common::BatchWriter. Every row carries rx_wall, rx_monotonic and
// capture_session (the logger's start time, one value per run).

using WallClock = std::chrono::system_clock;

inline WallClock::time_point wall_from_ns(int64_t ns) {
    return WallClock::time_point(std::chrono::duration_cast<WallClock::duration>(std::chrono::nanoseconds(ns)));
}

inline std::string opt_ts(const std::optional<WallClock::time_point>& t) {
    return t ? common::sql_timestamp(*t) : std::string("NULL");
}

inline std::string int_array(const std::vector<int>& v) {
    std::string s = "'{";
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i) s += ',';
        s += std::to_string(v[i]);
    }
    return s + "}'";
}

// drone.live_frame: an access unit from RTP, with its injection time if any.
struct LiveFrameRow {
    LiveFrame f;
    std::optional<WallClock::time_point> inject_wall;
    std::optional<double> inject_mono;
};
inline const char* kLiveFrameColumns =
    "rx_wall, rx_monotonic, capture_session, ssrc, segment, frame_idx, rtp_ts, seq_first, seq_last, "
    "n_packets, n_lost, complete, key, size, t_rx_ns, pts_ms, first_rx_kernel_ns, last_rx_kernel_ns, "
    "last_rx_monotonic, inject_wall, inject_monotonic";
inline std::string format_row(const LiveFrameRow& r, const std::string& session_sql) {
    const auto& f = r.f;
    const auto& e = f.ext;
    using common::sql_int;
    return std::format("({},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{})",
        common::sql_timestamp(wall_from_ns(f.wall_first_ns)), common::sql_float(f.mono_first), session_sql,
        sql_int(static_cast<long long>(f.ssrc)),
        e ? sql_int(static_cast<long long>(e->segment)) : "NULL",
        e ? sql_int(static_cast<long long>(e->frame_idx)) : "NULL",
        sql_int(static_cast<long long>(f.rtp_ts)), sql_int(f.seq_first), sql_int(f.seq_last),
        sql_int(f.n_packets), sql_int(f.n_lost), common::sql_bool(f.complete), common::sql_bool(f.key),
        sql_int(static_cast<long long>(f.size)),
        e ? sql_int(static_cast<long long>(e->t_rx_ns)) : "NULL",
        e ? sql_int(static_cast<long long>(e->pts_ms)) : "NULL",
        sql_int(f.kernel_first_ns), sql_int(f.kernel_last_ns), common::sql_float(f.mono_last),
        opt_ts(r.inject_wall), common::sql_float(r.inject_mono));
}

// Common receive fields of a message row.
struct MsgRx {
    WallClock::time_point wall;
    double mono = 0;
    std::optional<std::string> phone_session;
    std::optional<long long> seq;
    std::optional<long long> t_ph_ns;
};

// drone.phone_frame: a `frame` message.
struct PhoneFrameRow {
    MsgRx rx;
    std::optional<long long> segment, frame_idx, rtp_ts, rtp_seq_first, rtp_seq_last, t_rx_ns, t_tx_ns, pts_ms,
        size, sei_count, w, h, fps;
    std::optional<bool> key;
    std::vector<int> nal_types, sei_types;
    std::optional<std::string> mime;
};
inline const char* kPhoneFrameColumns =
    "rx_wall, rx_monotonic, capture_session, phone_session, seq, segment, frame_idx, rtp_ts, rtp_seq_first, "
    "rtp_seq_last, t_rx_ns, t_tx_ns, pts_ms, key, size, nal_types, sei_count, sei_types, w, h, fps, mime";
inline std::string format_row(const PhoneFrameRow& r, const std::string& session_sql) {
    using common::sql_int;
    return std::format("({},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{})",
        common::sql_timestamp(r.rx.wall), common::sql_float(r.rx.mono), session_sql,
        common::sql_text_opt(r.rx.phone_session), sql_int(r.rx.seq), sql_int(r.segment), sql_int(r.frame_idx),
        sql_int(r.rtp_ts), sql_int(r.rtp_seq_first), sql_int(r.rtp_seq_last), sql_int(r.t_rx_ns),
        sql_int(r.t_tx_ns), sql_int(r.pts_ms), r.key ? common::sql_bool(*r.key) : "NULL", sql_int(r.size),
        int_array(r.nal_types), sql_int(r.sei_count), int_array(r.sei_types), sql_int(r.w), sql_int(r.h),
        sql_int(r.fps), common::sql_text_opt(r.mime));
}

// drone.telemetry: a `telemetry` message (value = JSON text of the key value).
struct TelemetryRow {
    MsgRx rx;
    std::optional<std::string> key;
    std::string value_json;
};
inline const char* kTelemetryColumns =
    "rx_wall, rx_monotonic, capture_session, phone_session, seq, t_ph_ns, key, value";
inline std::string format_row(const TelemetryRow& r, const std::string& session_sql) {
    return std::format("({},{},{},{},{},{},{},{}::jsonb)",
        common::sql_timestamp(r.rx.wall), common::sql_float(r.rx.mono), session_sql,
        common::sql_text_opt(r.rx.phone_session), common::sql_int(r.rx.seq), common::sql_int(r.rx.t_ph_ns),
        common::sql_text_opt(r.key), common::sql_text(r.value_json));
}

// drone.event: an `event` or `key_rates` message (payload = the whole message).
struct EventRow {
    MsgRx rx;
    std::string type;
    std::string payload_json;
};
inline const char* kEventColumns =
    "rx_wall, rx_monotonic, capture_session, phone_session, seq, t_ph_ns, type, payload";
inline std::string format_row(const EventRow& r, const std::string& session_sql) {
    return std::format("({},{},{},{},{},{},{},{}::jsonb)",
        common::sql_timestamp(r.rx.wall), common::sql_float(r.rx.mono), session_sql,
        common::sql_text_opt(r.rx.phone_session), common::sql_int(r.rx.seq), common::sql_int(r.rx.t_ph_ns),
        common::sql_text(r.type), common::sql_text(r.payload_json));
}

// drone.clock_beacon: a `clock` message with its kernel receive time.
struct BeaconRow {
    MsgRx rx;
    int64_t rx_kernel_ns = 0;
};
inline const char* kBeaconColumns =
    "rx_wall, rx_monotonic, capture_session, phone_session, seq, t_ph_ns, rx_kernel_ns";
inline std::string format_row(const BeaconRow& r, const std::string& session_sql) {
    return std::format("({},{},{},{},{},{},{})",
        common::sql_timestamp(r.rx.wall), common::sql_float(r.rx.mono), session_sql,
        common::sql_text_opt(r.rx.phone_session), common::sql_int(r.rx.seq), common::sql_int(r.rx.t_ph_ns),
        common::sql_int(static_cast<long long>(r.rx_kernel_ns)));
}

// drone.config_check: one checked field (spec 8.5).
struct ConfigCheckRow {
    WallClock::time_point wall;
    double mono = 0;
    std::string field, expected, reported;
    bool ok = false;
};
inline const char* kConfigCheckColumns =
    "rx_wall, rx_monotonic, capture_session, field, expected, reported, ok";
inline std::string format_row(const ConfigCheckRow& r, const std::string& session_sql) {
    return std::format("({},{},{},{},{},{},{})",
        common::sql_timestamp(r.wall), common::sql_float(r.mono), session_sql, common::sql_text(r.field),
        common::sql_text(r.expected), common::sql_text(r.reported), common::sql_bool(r.ok));
}

}  // namespace drone
