#pragma once

#include "ivf_search.h"

#include <chrono>
#include <string>
#include <vector>

namespace ivf {

struct QueryStatistics {
    std::size_t candidates = 0, candidate_tasks = 0;
    std::size_t local_result_bytes = 0, descriptor_bytes = 0, exception_bytes = 0;
    std::size_t child_heap_upper_bound_bytes = 0;
    // Wall-clock intervals within one query. Queries may overlap: do not add
    // these across queries and interpret the sum as batch elapsed time.
    double select_ms = 0, partition_ms = 0, taskgroup_ms = 0, merge_ms = 0, scan_topk_ms = 0;
};

struct alignas(64) ThreadStatistics {
    std::size_t candidates = 0, candidate_tasks = 0, completed_queries = 0;
    int first_cpu = -1, last_cpu = -1;
};

struct SearchStatistics {
    int actual_threads = 0;
    std::vector<QueryStatistics> queries;
    std::vector<ThreadStatistics> threads;
    void reset(std::size_t count, int requested) {
        actual_threads = 0;
        queries.assign(count, QueryStatistics{});
        threads.assign(static_cast<std::size_t>(requested), ThreadStatistics{});
    }
};

using ProfileClock = std::chrono::steady_clock;
template <bool Enabled> ProfileClock::time_point profile_now() {
    if constexpr (Enabled) return ProfileClock::now();
    return {};
}
inline double elapsed_ms(ProfileClock::time_point begin) {
    return std::chrono::duration<double, std::milli>(ProfileClock::now() - begin).count();
}

int current_cpu();
void pin_current_thread(int cpu);
void record_work(ThreadStatistics& thread, std::size_t candidates,
                 std::size_t tasks, std::size_t queries);
// Instrumented equivalent loop for serial diagnostics. The timed serial
// implementation and independent reference in ivf_search.cpp stay unchanged.
void search_serial_diagnostics(const IVFIndex&, const float*, std::size_t,
                                const SearchOptions&, Neighbor*);

class PerfControl {
public:
    struct Record { std::string command; double ack_wait_ms; };
    PerfControl(const std::string& control, const std::string& ack,
                int timeout_ms, std::size_t repeats);
    ~PerfControl();
    PerfControl(const PerfControl&) = delete;
    PerfControl& operator=(const PerfControl&) = delete;
    void enable();
    void disable();
    void save_log(const std::string& path) const;

private:
    int control_fd_ = -1, ack_fd_ = -1, timeout_ms_;
    bool enabled_ = false;
    std::vector<Record> records_;
    void send(const std::string& command);
};

}  // namespace ivf
