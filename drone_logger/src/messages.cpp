#include "messages.hpp"

#include <nlohmann/json.hpp>

namespace drone {

namespace {

using nlohmann::json;

std::optional<long long> get_int(const json& j, const char* k) {
    auto it = j.find(k);
    if (it == j.end() || !it->is_number()) return std::nullopt;
    return it->is_number_float() ? static_cast<long long>(it->get<double>()) : it->get<long long>();
}

std::optional<std::string> get_str(const json& j, const char* k) {
    auto it = j.find(k);
    if (it == j.end() || !it->is_string()) return std::nullopt;
    return it->get<std::string>();
}

std::vector<int> get_int_array(const json& j) {
    std::vector<int> v;
    if (!j.is_array()) return v;
    for (const auto& x : j)
        if (x.is_number_integer()) v.push_back(x.get<int>());
    return v;
}

}  // namespace

Message parse_message(const uint8_t* data, std::size_t len, WallClock::time_point wall, double mono,
                      int64_t kernel_ns, MessageError* err) {
    json j = json::parse(data, data + len, nullptr, /*allow_exceptions=*/false);
    if (j.is_discarded() || !j.is_object()) {
        if (err) err->what = "invalid JSON";
        return std::monostate{};
    }
    const auto type = get_str(j, "type");
    if (!type) {
        if (err) err->what = "no type";
        return std::monostate{};
    }

    MsgRx rx;
    rx.wall = wall;
    rx.mono = mono;
    rx.phone_session = get_str(j, "phone_session");
    rx.seq = get_int(j, "seq");
    rx.t_ph_ns = get_int(j, "t_ph_ns");

    if (*type == "clock") {
        BeaconRow r;
        r.rx = rx;
        r.rx_kernel_ns = kernel_ns;
        return r;
    }
    if (*type == "telemetry") {
        TelemetryRow r;
        r.rx = rx;
        r.key = get_str(j, "key");
        auto it = j.find("value");
        r.value_json = it == j.end() ? "null" : it->dump();
        return r;
    }
    if (*type == "event" || *type == "key_rates") {
        EventRow r;
        r.rx = rx;
        r.type = *type == "event" ? get_str(j, "event").value_or("event") : "key_rates";
        r.payload_json = j.dump();
        return r;
    }
    if (*type == "frame") {
        PhoneFrameRow r;
        r.rx = rx;
        r.segment = get_int(j, "segment");
        r.frame_idx = get_int(j, "frame_idx");
        r.rtp_ts = get_int(j, "rtp_ts");
        r.rtp_seq_first = get_int(j, "rtp_seq_first");
        r.rtp_seq_last = get_int(j, "rtp_seq_last");
        r.t_rx_ns = get_int(j, "t_rx_ns");
        r.t_tx_ns = get_int(j, "t_tx_ns");
        r.pts_ms = get_int(j, "pts_ms");
        r.size = get_int(j, "size");
        r.w = get_int(j, "w");
        r.h = get_int(j, "h");
        r.fps = get_int(j, "fps");
        r.mime = get_str(j, "mime");
        if (auto it = j.find("key"); it != j.end() && it->is_boolean()) r.key = it->get<bool>();
        if (auto it = j.find("nal_types"); it != j.end()) r.nal_types = get_int_array(*it);
        if (auto it = j.find("sei"); it != j.end() && it->is_object()) {
            r.sei_count = get_int(*it, "count");
            if (auto t = it->find("types"); t != it->end()) r.sei_types = get_int_array(*t);
        }
        return r;
    }
    if (err) err->what = "unknown type " + *type;
    return std::monostate{};
}

}  // namespace drone
