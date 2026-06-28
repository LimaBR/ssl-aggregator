#pragma once
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <utility>

namespace common {

// Simple multi-producer / single-consumer queue. The RX thread pushes decoded
// rows; the DB worker pops and batches them.
template <typename T>
class BlockingQueue {
public:
    void push(T value) {
        {
            std::lock_guard<std::mutex> lk(m_);
            q_.push_back(std::move(value));
        }
        cv_.notify_one();
    }

    // Wait up to `timeout` for an item. Returns true and moves it into `out`,
    // or false if the timeout elapsed with the queue empty.
    bool wait_pop(T& out, std::chrono::milliseconds timeout) {
        std::unique_lock<std::mutex> lk(m_);
        if (!cv_.wait_for(lk, timeout, [this] { return !q_.empty(); }))
            return false;
        out = std::move(q_.front());
        q_.pop_front();
        return true;
    }

    std::size_t size() const {
        std::lock_guard<std::mutex> lk(m_);
        return q_.size();
    }

private:
    mutable std::mutex m_;
    std::condition_variable cv_;
    std::deque<T> q_;
};

}  // namespace common
