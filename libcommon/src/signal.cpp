#include "common/signal.hpp"

#include <csignal>

namespace common {

namespace {
std::atomic<bool>* g_flag = nullptr;

void handler(int) {
    if (g_flag) g_flag->store(true);
}
}  // namespace

void install_shutdown_handler(std::atomic<bool>* flag) {
    g_flag = flag;
    std::signal(SIGINT, handler);
    std::signal(SIGTERM, handler);
}

}  // namespace common
