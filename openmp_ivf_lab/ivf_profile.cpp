#include "ivf_profile.h"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <poll.h>
#include <stdexcept>
#include <sys/stat.h>
#include <system_error>
#include <unistd.h>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace ivf {

int current_cpu() {
#ifdef __linux__
    return sched_getcpu();
#else
    return -1;
#endif
}

void pin_current_thread(int cpu) {
#ifdef __linux__
    if (cpu < 0 || cpu >= CPU_SETSIZE) throw std::invalid_argument("CPU ID outside CPU_SETSIZE");
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cpu, &mask);
    const int error = pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);
    if (error) throw std::system_error(error, std::generic_category(), "pthread_setaffinity_np");
#else
    (void)cpu;
    throw std::invalid_argument("--pin-cpus requires Linux");
#endif
}

void record_work(ThreadStatistics& thread, std::size_t candidates,
                 std::size_t tasks, std::size_t queries) {
    thread.candidates += candidates;
    thread.candidate_tasks += tasks;
    thread.completed_queries += queries;
    const auto cpu = current_cpu();
    if (thread.first_cpu == -1) thread.first_cpu = cpu;
    thread.last_cpu = cpu;
}

PerfControl::PerfControl(const std::string& control, const std::string& ack,
                         int timeout_ms, std::size_t repeats) : timeout_ms_(timeout_ms) {
    records_.reserve(2 * repeats);
    try {
        // RDWR/nonblocking avoids FIFO-open deadlocks. A missing controller is
        // diagnosed by the bounded acknowledgement wait rather than hanging.
        control_fd_ = open(control.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
        if (control_fd_ == -1) throw std::system_error(errno, std::generic_category(), "open perf control");
        ack_fd_ = open(ack.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
        if (ack_fd_ == -1) throw std::system_error(errno, std::generic_category(), "open perf ack");
        struct stat status{};
        if (fstat(control_fd_, &status) || !S_ISFIFO(status.st_mode) ||
            fstat(ack_fd_, &status) || !S_ISFIFO(status.st_mode)) {
            throw std::invalid_argument("perf control and ack must be named FIFOs");
        }
    } catch (...) {
        if (control_fd_ != -1) close(control_fd_);
        if (ack_fd_ != -1) close(ack_fd_);
        throw;
    }
}

PerfControl::~PerfControl() {
    if (control_fd_ != -1) close(control_fd_);
    if (ack_fd_ != -1) close(ack_fd_);
}

void PerfControl::send(const std::string& command) {
    const auto start = ProfileClock::now();
    const auto deadline = start + std::chrono::milliseconds(timeout_ms_);
    const auto message = command + '\n';
    std::size_t sent = 0;
    std::string response;
    while (sent < message.size()) {
        const auto n = write(control_fd_, message.data() + sent, message.size() - sent);
        if (n > 0) sent += static_cast<std::size_t>(n);
        else if (n == -1 && errno != EINTR && errno != EAGAIN) {
            throw std::system_error(errno, std::generic_category(), "write perf control");
        }
        if (ProfileClock::now() >= deadline) throw std::runtime_error("perf control write timeout");
    }
    for (;;) {
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - ProfileClock::now()).count();
        if (remaining <= 0) throw std::runtime_error("perf acknowledgement timeout for " + command);
        pollfd descriptor{ack_fd_, POLLIN, 0};
        const int ready = poll(&descriptor, 1, static_cast<int>(remaining));
        if (ready == -1 && errno == EINTR) continue;
        if (ready == -1) throw std::system_error(errno, std::generic_category(), "poll perf ack");
        if (!ready) continue;
        char buffer[128];
        const auto n = read(ack_fd_, buffer, sizeof(buffer));
        if (n > 0) response.append(buffer, static_cast<std::size_t>(n));
        else if (n == -1 && errno != EAGAIN && errno != EINTR) {
            throw std::system_error(errno, std::generic_category(), "read perf ack");
        }
        if (response.size() > 128) throw std::runtime_error("invalid perf acknowledgement");
        // perf versions/controllers delimit the acknowledgement with a newline
        // and/or a NUL. Accept the exact ack token with either framing.
        const std::string delimiters("\0\n\r ", 4);
        const auto first = response.find_first_not_of(delimiters);
        if (first != std::string::npos) {
            const auto last = response.find_last_not_of(delimiters);
            const auto token = response.substr(first, last - first + 1);
            if (token == "ack") break;
            if (token.size() > 3 || std::string("ack").compare(0, token.size(), token) != 0) {
                throw std::runtime_error("unexpected perf acknowledgement: " + response);
            }
        }
    }
    records_.push_back({command, elapsed_ms(start)});
}

void PerfControl::enable() {
    if (enabled_) throw std::logic_error("perf counters already enabled");
    send("enable");
    enabled_ = true;
}

void PerfControl::disable() {
    if (!enabled_) throw std::logic_error("perf counters already disabled");
    send("disable");
    enabled_ = false;
}

void PerfControl::save_log(const std::string& path) const {
    if (path.empty()) return;
    std::ofstream out;
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.open(path);
    out << "command,ack_wait_ms\n" << std::setprecision(12);
    for (const auto& record : records_) out << record.command << ',' << record.ack_wait_ms << '\n';
}

}  // namespace ivf
