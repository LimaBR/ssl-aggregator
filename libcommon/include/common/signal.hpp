#pragma once
#include <atomic>

namespace common {

// Install a SIGINT/SIGTERM handler that sets *flag to true, so the main loop
// can shut down cleanly (flush pending DB rows, join threads).
void install_shutdown_handler(std::atomic<bool>* flag);

}  // namespace common
