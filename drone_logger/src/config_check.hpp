#pragma once
#include <map>
#include <optional>
#include <print>
#include <sstream>
#include <string>
#include <vector>

#include "db_rows.hpp"

namespace drone {

// Configuration check (dji-relay spec 8.5): the live stream's reported values
// against the expected profile in .env. F4 checks w, h, fps and mime from the
// phone's `frame` messages; the camera settings are added in F5.
//
// Each DRONE_EXPECT_* key holds one accepted value or a comma-separated list
// (e.g. DRONE_EXPECT_FPS=59,60). An unset key is not checked. A row is written
// to drone.config_check whenever the reported value of a checked field changes;
// mismatches are also printed prominently.
class ConfigChecker {
public:
    void expect(const std::string& field, const std::string& accepted_csv) {
        if (accepted_csv.empty()) return;
        std::vector<std::string> values;
        std::stringstream ss(accepted_csv);
        for (std::string v; std::getline(ss, v, ',');) {
            if (!v.empty()) values.push_back(v);
        }
        if (!values.empty()) expected_[field] = {accepted_csv, values};
    }

    bool enabled() const { return !expected_.empty(); }

    // Checks one reported value; returns a row if the value changed since the last report.
    std::optional<ConfigCheckRow> report(const std::string& field, const std::string& value,
                                         WallClock::time_point wall, double mono) {
        auto it = expected_.find(field);
        if (it == expected_.end()) return std::nullopt;
        auto& last = last_[field];
        if (last && *last == value) return std::nullopt;
        last = value;

        bool ok = false;
        for (const auto& v : it->second.values) ok = ok || v == value;
        if (!ok) {
            ++mismatches_;
            std::println(stderr, "\n*** drone_logger CONFIG MISMATCH: {} = {} (expected {}) ***\n", field, value,
                         it->second.csv);
        }
        return ConfigCheckRow{wall, mono, field, it->second.csv, value, ok};
    }

    uint64_t mismatches() const { return mismatches_; }

private:
    struct Expected {
        std::string csv;
        std::vector<std::string> values;
    };
    std::map<std::string, Expected> expected_;
    std::map<std::string, std::optional<std::string>> last_;
    uint64_t mismatches_ = 0;
};

}  // namespace drone
