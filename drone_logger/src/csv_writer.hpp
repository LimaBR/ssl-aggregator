#pragma once
#include <atomic>
#include <chrono>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <thread>

#include "common/blocking_queue.hpp"

namespace drone {

// Appends lines to a CSV file from a dedicated thread, so the receive loop
// never waits on the disk. Every line pushed is written (no silent drops);
// the file is flushed about once per second and on close.
class CsvWriter {
public:
    CsvWriter(const std::string& path, const std::string& header) : path_(path) {
        f_ = std::fopen(path.c_str(), "w");
        if (!f_) throw std::runtime_error("cannot open " + path);
        std::fputs(header.c_str(), f_);
        std::fputc('\n', f_);
        thread_ = std::jthread([this] { run(); });
    }

    ~CsvWriter() { close(); }
    CsvWriter(const CsvWriter&) = delete;
    CsvWriter& operator=(const CsvWriter&) = delete;

    void push(std::string line) { q_.push(std::move(line)); }

    // Writes everything still queued, then closes the file.
    void close() {
        if (!f_) return;
        stop_.store(true);
        if (thread_.joinable()) thread_.join();
        std::fclose(f_);
        f_ = nullptr;
    }

    std::size_t backlog() const { return q_.size(); }
    uint64_t lines() const { return lines_.load(); }
    const std::string& path() const { return path_; }

private:
    void run() {
        using namespace std::chrono;
        auto last_flush = steady_clock::now();
        std::string line;
        while (true) {
            const bool got = q_.wait_pop(line, milliseconds(200));
            if (got) {
                std::fputs(line.c_str(), f_);
                std::fputc('\n', f_);
                lines_.fetch_add(1);
            }
            const auto now = steady_clock::now();
            if (now - last_flush >= seconds(1)) {
                std::fflush(f_);
                last_flush = now;
            }
            if (!got && stop_.load() && q_.size() == 0) break;
        }
        std::fflush(f_);
    }

    std::string path_;
    std::FILE* f_ = nullptr;
    common::BlockingQueue<std::string> q_;
    std::atomic<bool> stop_{false};
    std::atomic<uint64_t> lines_{0};
    std::jthread thread_;
};

}  // namespace drone
