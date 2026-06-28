#pragma once
#include <string>

namespace common {

// Load KEY=VALUE pairs from a .env file into the process environment. Existing
// environment variables are NOT overwritten, so a real env var still wins (handy
// for one-off overrides). Lines starting with '#' and blank lines are ignored;
// an optional "export " prefix and surrounding quotes are stripped. Returns
// false if the file does not exist. Call this before reading any config keys.
bool load_dotenv(const std::string& path = ".env");

// Tiny environment-variable config helpers. Each logger reads its own keys.
std::string env_str(const char* key, const std::string& fallback);
int env_int(const char* key, int fallback);

}  // namespace common
