#pragma once
#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <print>
#include <string>
#include <thread>
#include <vector>

#include <pqxx/pqxx>

#include "common/blocking_queue.hpp"

namespace common {

// Drains a BlockingQueue<Row> and writes rows to Postgres in batches, flushing
// when either `batch_size` rows are buffered or `max_latency` has elapsed.
//
// Each Row is turned into a "(v1, v2, ...)" VALUES tuple by `Formatter`; the
// writer assembles one plain multi-row INSERT per flush. There is deliberately
// no ON CONFLICT clause: every parsed packet is stored, so a firmware reboot
// (which restarts packet_id) can never cause a row to be silently dropped.
template <typename Row>
class BatchWriter {
public:
    using Formatter = std::function<std::string(const Row&)>;

    BatchWriter(std::string conninfo, std::string table,
                std::string columns_csv, Formatter fmt,
                std::size_t batch_size, std::chrono::milliseconds max_latency)
        : conninfo_(std::move(conninfo)),
          table_(std::move(table)),
          columns_csv_(std::move(columns_csv)),
          fmt_(std::move(fmt)),
          batch_size_(batch_size),
          max_latency_(max_latency) {}

    // Runs on the DB worker thread until `stop` is set and the queue is drained.
    // Connection is established lazily in flush() (with retries), so the worker
    // tolerates the database being unavailable at startup.
    void run(BlockingQueue<Row>& queue, std::atomic<bool>& stop) {
        std::vector<Row> batch;
        batch.reserve(batch_size_);
        auto last_flush = std::chrono::steady_clock::now();

        while (true) {
            Row row;
            bool got = queue.wait_pop(row, std::chrono::milliseconds(50));
            if (got) batch.push_back(std::move(row));

            auto now = std::chrono::steady_clock::now();
            bool size_full = batch.size() >= batch_size_;
            bool aged = !batch.empty() && (now - last_flush) >= max_latency_;
            if (size_full || aged) {
                flush(batch);
                batch.clear();
                last_flush = now;
            }

            if (stop.load() && !got) {
                while (queue.wait_pop(row, std::chrono::milliseconds(0)))
                    batch.push_back(std::move(row));
                if (!batch.empty()) flush(batch);
                break;
            }
        }
    }

private:
    void connect() {
        conn_ = std::make_unique<pqxx::connection>(conninfo_);
    }

    void flush(const std::vector<Row>& batch) {
        std::string sql = "INSERT INTO " + table_ + " (" + columns_csv_ +
                          ") VALUES ";
        for (std::size_t i = 0; i < batch.size(); ++i) {
            if (i) sql += ',';
            sql += fmt_(batch[i]);
        }
        sql += ';';

        for (int attempt = 0; attempt < 3; ++attempt) {
            try {
                if (!conn_ || !conn_->is_open()) connect();
                pqxx::work tx{*conn_};
                tx.exec(sql);
                tx.commit();
                return;
            } catch (const std::exception& e) {
                std::println(stderr, "[db] flush failed (attempt {}/3): {}",
                             attempt + 1, e.what());
                std::this_thread::sleep_for(std::chrono::milliseconds(500));
                try { connect(); } catch (...) {}
            }
        }
        std::println(stderr, "[db] dropping batch of {} rows after retries",
                     batch.size());
    }

    std::string conninfo_;
    std::string table_;
    std::string columns_csv_;
    Formatter fmt_;
    std::size_t batch_size_;
    std::chrono::milliseconds max_latency_;
    std::unique_ptr<pqxx::connection> conn_;
};

}  // namespace common
