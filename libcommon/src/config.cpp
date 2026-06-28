#include "common/config.hpp"

#include <cstdlib>
#include <fstream>
#include <stdexcept>

namespace common {

namespace {
std::string trim(const std::string& s) {
    const char* ws = " \t\r\n";
    auto b = s.find_first_not_of(ws);
    if (b == std::string::npos) return "";
    return s.substr(b, s.find_last_not_of(ws) - b + 1);
}
}  // namespace

bool load_dotenv(const std::string& path) {
    std::ifstream f(path);
    if (!f) return false;

    std::string line;
    while (std::getline(f, line)) {
        std::string s = trim(line);
        if (s.empty() || s[0] == '#') continue;
        if (s.rfind("export ", 0) == 0) s = trim(s.substr(7));

        auto eq = s.find('=');
        if (eq == std::string::npos) continue;
        std::string key = trim(s.substr(0, eq));
        std::string val = trim(s.substr(eq + 1));
        if (key.empty()) continue;

        if (val.size() >= 2 &&
            ((val.front() == '"' && val.back() == '"') ||
             (val.front() == '\'' && val.back() == '\'')))
            val = val.substr(1, val.size() - 2);

        ::setenv(key.c_str(), val.c_str(), /*overwrite=*/0);
    }
    return true;
}

std::string env_str(const char* key, const std::string& fallback) {
    const char* v = std::getenv(key);
    return v ? std::string(v) : fallback;
}

int env_int(const char* key, int fallback) {
    const char* v = std::getenv(key);
    if (!v || *v == '\0') return fallback;
    try {
        return std::stoi(v);
    } catch (const std::exception&) {
        return fallback;
    }
}

}  // namespace common
