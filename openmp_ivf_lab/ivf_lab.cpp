#include "ivf_search.h"
#include "ivf_profile.h"

#include <omp.h>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <climits>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>

struct Arguments {
    std::string base = "/var/dataset/sift_base.fbin";
    std::string centroids = "/var/dataset/centroid_4096.fvecs";
    std::string cluster_ids = "/var/dataset/cluster_id_4096.ivecs";
    std::string queries_file = "/var/dataset/sift_query.fbin";
    std::string groundtruth = "/var/dataset/gt.ibin";
    std::string only = "serial", mode = "bench", csv;
    std::string query_order = "original", order_csv, batches_csv, stats_prefix;
    std::string perf_control, perf_ack, perf_log;
    int perf_timeout_ms = 10000;
    std::size_t queries = 128, batch = 32, repeats = 10, warmup = 1;
    ivf::SearchOptions search;
};

std::size_t number(const std::string& value) {
    std::size_t n;
    const auto result = std::from_chars(value.data(), value.data() + value.size(), n);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size()) {
        throw std::invalid_argument("invalid integer: " + value);
    }
    return n;
}

std::vector<int> cpu_list(const std::string& value) {
    std::vector<int> cpus;
    std::size_t begin = 0;
    while (begin < value.size()) {
        const auto end = value.find(',', begin);
        const auto n = number(value.substr(begin, end - begin));
        if (n > INT_MAX || std::find(cpus.begin(), cpus.end(), static_cast<int>(n)) != cpus.end()) {
            throw std::invalid_argument("invalid or duplicate CPU ID");
        }
        cpus.push_back(static_cast<int>(n));
        if (end == std::string::npos) break;
        begin = end + 1;
        if (begin == value.size()) throw std::invalid_argument("trailing comma in CPU list");
    }
    if (cpus.empty()) throw std::invalid_argument("empty CPU list");
    return cpus;
}

Arguments parse(int argc, char** argv) {
    Arguments args;
    for (int i = 1; i < argc; i += 2) {
        const std::string key = argv[i];
        if (i + 1 == argc) throw std::invalid_argument("missing value for " + key);
        const std::string value = argv[i + 1];
        if (key == "--base") args.base = value;
        else if (key == "--centroids") args.centroids = value;
        else if (key == "--cluster-ids") args.cluster_ids = value;
        else if (key == "--queries-file") args.queries_file = value;
        else if (key == "--gt") args.groundtruth = value;
        else if (key == "--only") args.only = value;
        else if (key == "--mode") args.mode = value;
        else if (key == "--csv") args.csv = value;
        else if (key == "--query-order") args.query_order = value;
        else if (key == "--order-csv") args.order_csv = value;
        else if (key == "--batches-csv") args.batches_csv = value;
        else if (key == "--stats-prefix") args.stats_prefix = value;
        else if (key == "--perf-control") args.perf_control = value;
        else if (key == "--perf-ack") args.perf_ack = value;
        else if (key == "--perf-log") args.perf_log = value;
        else if (key == "--pin-cpus") args.search.pin_cpus = cpu_list(value);
        else if (key == "--queries") args.queries = number(value);
        else if (key == "--batch") args.batch = number(value);
        else if (key == "--repeats") args.repeats = number(value);
        else if (key == "--warmup") args.warmup = number(value);
        else if (key == "--k") args.search.k = number(value);
        else if (key == "--nprobe") args.search.nprobe = number(value);
        else if (key == "--grain") args.search.grain = number(value);
        else if (key == "--simd") {
            if (value != "on" && value != "off") throw std::invalid_argument("--simd expects on or off");
            args.search.simd = value == "on";
        } else if (key == "--threads" || key == "--perf-timeout-ms") {
            const auto n = number(value);
            if (n == 0 || n > INT_MAX) throw std::invalid_argument("invalid count for " + key);
            if (key == "--threads") args.search.threads = static_cast<int>(n);
            else args.perf_timeout_ms = static_cast<int>(n);
        } else throw std::invalid_argument("unknown option: " + key);
    }
    if (!args.queries || !args.batch || !args.repeats || !args.search.k ||
        !args.search.nprobe || !args.search.grain) {
        throw std::invalid_argument("counts must be positive (except warmup)");
    }
    if (args.mode != "check" && args.mode != "bench" && args.mode != "stats") {
        throw std::invalid_argument("--mode expects check, bench or stats");
    }
    if (args.search.simd && args.only != "omp1" && args.only != "omp2") {
        throw std::invalid_argument("--simd on requires --only omp1 or omp2");
    }
    if (args.query_order != "original" && args.query_order != "candidates-asc" &&
        args.query_order != "candidates-desc") {
        throw std::invalid_argument("unknown --query-order");
    }
    if ((args.mode == "stats") != !args.stats_prefix.empty()) {
        throw std::invalid_argument("--mode stats requires --stats-prefix, used only in stats mode");
    }
    if (args.mode == "stats" && args.only == "exact") {
        throw std::invalid_argument("stats supports serial, std, omp1 and omp2");
    }
    if (!args.batches_csv.empty() && args.mode != "bench") {
        throw std::invalid_argument("--batches-csv is for bench mode");
    }
    if (args.perf_control.empty() != args.perf_ack.empty() ||
        (!args.perf_log.empty() && args.perf_control.empty())) {
        throw std::invalid_argument("perf requires both --perf-control and --perf-ack");
    }
    if (!args.perf_control.empty() && (args.mode != "bench" || !args.warmup ||
                                      args.perf_control == args.perf_ack)) {
        throw std::invalid_argument("perf requires bench mode, warmup>=1 and distinct FIFOs");
    }
    return args;
}

ivf::SearchFunction select_strategy(const std::string& name) {
    if (name == "serial") return ivf::search_ivf_serial;
    if (name == "std") return ivf::search_std_thread;
    if (name == "exact") return ivf::search_exact_serial;
    if (name == "omp1") return ivf::search_omp_student_1;
    if (name == "omp2") return ivf::search_omp_student_2;
    throw std::invalid_argument("unknown strategy: " + name);
}

std::ofstream output_file(const std::string& path) {
    std::ofstream out;
    out.exceptions(std::ios::failbit | std::ios::badbit);
    out.open(path);
    out << std::setprecision(12);
    return out;
}

void diagnostics(const Arguments& args, const ivf::IVFIndex& index,
                  const ivf::FloatMatrix& queries, const std::vector<std::size_t>& order,
                  const std::vector<std::size_t>& candidates,
                  const std::vector<ivf::Neighbor>& reference, std::vector<ivf::Neighbor>& output,
                  ivf::SearchFunction search) {
    auto per_query = output_file(args.stats_prefix + "_queries.csv");
    auto per_thread = output_file(args.stats_prefix + "_threads.csv");
    auto per_batch = output_file(args.stats_prefix + "_batches.csv");
    auto per_list = output_file(args.stats_prefix + "_lists.csv");
    per_query << "strategy,simd,requested_threads,actual_threads,batch_index,query_ordinal,original_query_id,"
                 "candidates,candidate_tasks,parent_tasks,local_result_bytes,descriptor_bytes,exception_bytes,"
                 "child_heap_upper_bound_bytes,select_query_wall_ms,partition_query_wall_ms,taskgroup_query_wall_ms,"
                 "merge_query_wall_ms,scan_topk_query_wall_ms\n";
    per_thread << "strategy,simd,requested_threads,actual_threads,batch_index,thread_id,candidates,"
                  "candidate_tasks,completed_queries,first_cpu,last_cpu\n";
    per_batch << "strategy,simd,batch_index,query_count,actual_threads,active_candidate_threads,"
                 "candidates,child_tasks,diagnostic_wall_ms\n";
    per_list << "list_id,length\n";
    for (std::size_t l = 0; l < index.nlist; ++l) {
        per_list << l << ',' << index.list_ptr[l + 1] - index.list_ptr[l] << '\n';
    }
    ivf::SearchStatistics stats;
    auto options = args.search;
    options.statistics = &stats;
    if (args.only == "serial") search = ivf::search_serial_diagnostics;
    std::fill(output.begin(), output.end(), ivf::Neighbor{std::numeric_limits<double>::quiet_NaN(), -2});
    const auto simd = args.search.simd ? "on" : "off";
    std::size_t batch_index = 0;
    for (std::size_t begin = 0; begin < args.queries; begin += args.batch, ++batch_index) {
        const auto count = std::min(args.batch, args.queries - begin);
        const auto start = ivf::ProfileClock::now();
        search(index, queries.row(begin), count, options, output.data() + begin * options.k);
        const auto wall_ms = ivf::elapsed_ms(start);
        if (stats.queries.size() != count || stats.actual_threads <= 0 ||
            std::size_t(stats.actual_threads) > stats.threads.size()) {
            throw std::runtime_error("invalid diagnostic team size");
        }
        std::size_t total = 0, tasks = 0, work = 0, active = 0, completed = 0, thread_tasks = 0;
        for (std::size_t q = 0; q < count; ++q) {
            const auto& s = stats.queries[q];
            if (s.candidates != candidates[order[begin + q]]) {
                throw std::runtime_error("candidate count differs from independent center selection");
            }
            total += s.candidates;
            tasks += s.candidate_tasks;
            per_query << args.only << ',' << simd << ',' << options.threads << ',' << stats.actual_threads << ','
                      << batch_index << ',' << begin + q << ',' << order[begin + q] << ',' << s.candidates << ','
                      << s.candidate_tasks << ',' << (args.only == "omp2" ? 1 : 0) << ','
                      << s.local_result_bytes << ',' << s.descriptor_bytes << ',' << s.exception_bytes << ','
                      << s.child_heap_upper_bound_bytes << ',' << s.select_ms << ',' << s.partition_ms << ','
                      << s.taskgroup_ms << ',' << s.merge_ms << ',' << s.scan_topk_ms << '\n';
        }
        for (int t = 0; t < stats.actual_threads; ++t) {
            const auto& s = stats.threads[t];
            work += s.candidates;
            thread_tasks += s.candidate_tasks;
            completed += s.completed_queries;
            active += s.candidates > 0;
            if (!options.pin_cpus.empty() && s.first_cpu >= 0 &&
                (std::find(options.pin_cpus.begin(), options.pin_cpus.end(), s.first_cpu) == options.pin_cpus.end() ||
                 std::find(options.pin_cpus.begin(), options.pin_cpus.end(), s.last_cpu) == options.pin_cpus.end())) {
                throw std::runtime_error("diagnostic worker observed outside configured CPU set");
            }
            per_thread << args.only << ',' << simd << ',' << options.threads << ',' << stats.actual_threads << ','
                       << batch_index << ',' << t << ',' << s.candidates << ',' << s.candidate_tasks << ','
                       << s.completed_queries << ',' << s.first_cpu << ',' << s.last_cpu << '\n';
        }
        if (total != work || tasks != thread_tasks || completed != count) {
            throw std::runtime_error("thread candidate/task/query totals do not reconcile");
        }
        per_batch << args.only << ',' << simd << ',' << batch_index << ',' << count << ',' << stats.actual_threads
                  << ',' << active << ',' << total << ',' << tasks << ',' << wall_ms << '\n';
    }
    ivf::check_result(output, reference);
    std::cout << "statistics=PASS (separate diagnostic run; per-query wall intervals may overlap)\n";
}

int run(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "SIFT IVF-Flat lab\n"
            "  --only serial|std|exact|omp1|omp2   --mode check|bench|stats\n"
            "  --queries 128   --batch 32   --k 10   --nprobe 8\n"
            "  --threads 4   --grain 1024   --repeats 10   --warmup 1\n"
            "  --simd off|on (on is supported by omp1/omp2 only)\n"
            "  --query-order original|candidates-asc|candidates-desc   --order-csv PATH\n"
            "  --batches-csv PATH (bench)   --stats-prefix PATH (stats; writes 4 CSVs)\n"
            "  --pin-cpus 0,1,2,3 (Linux; main on first CPU, std workers bound individually)\n"
            "  --perf-control FIFO --perf-ack FIFO --perf-log PATH --perf-timeout-ms 10000\n"
            "  --base PATH (.fbin)   --centroids PATH (.fvecs)\n"
            "  --cluster-ids PATH (.ivecs)   --queries-file PATH (.fbin)\n"
            "  --gt PATH (.ibin)   --csv PATH\n";
        return 0;
    }
    auto args = parse(argc, argv);
    const auto search = select_strategy(args.only);
    const auto index = ivf::read_ivf(args.base, args.centroids, args.cluster_ids);
    const auto input_queries = ivf::read_fbin(args.queries_file);
    const auto input_truth = ivf::read_ibin(args.groundtruth);
    if (args.only == "exact") args.search.nprobe = index.nlist;
    if (args.only == "serial" || args.only == "exact") args.search.threads = 1;
    if (input_queries.dim != index.dim || args.queries > input_queries.rows || args.queries > input_truth.rows ||
        args.search.k > index.size || args.search.k > input_truth.dim || args.search.nprobe > index.nlist) {
        throw std::invalid_argument("query count, dimension, k or nprobe exceeds input bounds");
    }
    for (std::size_t q = 0; q < args.queries; ++q) {
        const auto* row = input_truth.row(q);
        for (std::size_t j = 0; j < args.search.k; ++j) {
            if (row[j] < 0 || std::size_t(row[j]) >= index.size ||
                std::find(row, row + j, row[j]) != row + j) {
                throw std::invalid_argument("invalid or duplicate ground truth ID");
            }
        }
    }
    omp_set_dynamic(0);
    omp_set_num_threads(args.search.threads);
    // Initialize runtime topology before narrowing the calling thread's mask.
    (void)omp_get_num_procs();
    if (!args.search.pin_cpus.empty()) ivf::pin_current_thread(args.search.pin_cpus.front());
    std::vector<std::size_t> order(args.queries), candidates(args.queries);
    std::iota(order.begin(), order.end(), 0);
    if (args.mode == "stats" || args.query_order != "original" || !args.order_csv.empty()) {
        // This prepass arranges/validates the experiment. Every search invocation
        // still recomputes its own scalar center selection inside the timed call.
        for (std::size_t q = 0; q < args.queries; ++q) {
            for (const auto list : ivf::select_lists(index, input_queries.row(q), args.search.nprobe)) {
                candidates[q] += index.list_ptr[list + 1] - index.list_ptr[list];
            }
        }
    }
    if (args.query_order != "original") {
        std::stable_sort(order.begin(), order.end(), [&](auto a, auto b) {
            return args.query_order == "candidates-asc" ? candidates[a] < candidates[b]
                                                       : candidates[a] > candidates[b];
        });
    }
    ivf::FloatMatrix queries{args.queries, index.dim, std::vector<float>(args.queries * index.dim)};
    ivf::IntMatrix truth{args.queries, input_truth.dim, std::vector<std::int32_t>(args.queries * input_truth.dim)};
    for (std::size_t q = 0; q < args.queries; ++q) {
        std::copy_n(input_queries.row(order[q]), index.dim, queries.data.data() + q * index.dim);
        std::copy_n(input_truth.row(order[q]), truth.dim, truth.data.data() + q * truth.dim);
    }
    if (!args.order_csv.empty()) {
        auto out = output_file(args.order_csv);
        out << "query_ordinal,original_query_id,candidates\n";
        for (std::size_t q = 0; q < args.queries; ++q) out << q << ',' << order[q] << ',' << candidates[order[q]] << '\n';
    }
    std::cout << "N=" << index.size << " dim=" << index.dim << " nlist=" << index.nlist
              << " strategy=" << args.only << " threads=" << args.search.threads
              << " simd=" << (args.search.simd ? "on" : "off") << " query_order=" << args.query_order << '\n';
    std::vector<ivf::Neighbor> reference(args.queries * args.search.k), output(reference.size());
    const auto reference_search = args.search.nprobe == index.nlist
        ? ivf::search_exact_serial : ivf::search_ivf_serial;
    reference_search(index, queries.data.data(), args.queries, args.search, reference.data());
    const double recall = ivf::recall_at_k(reference, truth, args.queries, args.search.k);
    std::cout << std::fixed << std::setprecision(6);
    if (args.mode == "stats") {
        diagnostics(args, index, queries, order, candidates, reference, output, search);
        std::cout << "correctness=PASS recall@" << args.search.k << '=' << recall << '\n';
        return 0;
    }
    struct BatchSample { std::size_t begin, count; double ms; };
    std::vector<BatchSample> samples;
    if (!args.batches_csv.empty()) samples.reserve(1 + (args.queries - 1) / args.batch);
    std::unique_ptr<ivf::PerfControl> perf;
    auto run_once = [&] {
        std::fill(output.begin(), output.end(), ivf::Neighbor{std::numeric_limits<double>::quiet_NaN(), -2});
        samples.clear();
        double ms = 0;
        if (perf) perf->enable();
        try {
            for (std::size_t begin = 0; begin < args.queries; begin += args.batch) {
                const auto count = std::min(args.batch, args.queries - begin);
                const auto start = ivf::ProfileClock::now();
                search(index, queries.row(begin), count, args.search, output.data() + begin * args.search.k);
                const double elapsed = ivf::elapsed_ms(start);
                ms += elapsed;
                if (!args.batches_csv.empty()) samples.push_back({begin, count, elapsed});
            }
        } catch (...) {
            if (perf) {
                try { perf->disable(); } catch (...) { }
            }
            throw;
        }
        if (perf) perf->disable();
        ivf::check_result(output, reference);
        return ms;
    };
    if (args.mode == "check") {
        run_once();
        std::cout << "correctness=PASS recall@" << args.search.k << '=' << recall << '\n';
        return 0;
    }
    std::ofstream csv, batches;
    if (!args.csv.empty()) {
        csv = output_file(args.csv);
        csv << "strategy,threads,queries,batch,k,nprobe,grain,simd,query_order,repeat,time_ms,qps,recall,correctness\n";
    }
    if (!args.batches_csv.empty()) {
        batches = output_file(args.batches_csv);
        batches << "strategy,simd,query_order,threads,repeat,batch_index,query_begin,query_count,batch_time_ms\n";
    }
    for (std::size_t r = 0; r < args.warmup; ++r) run_once();
    // perf stat starts disabled with --delay=-1. Loading, reference generation
    // and warmups finish before the first enable command is sent.
    if (!args.perf_control.empty()) {
        perf = std::make_unique<ivf::PerfControl>(args.perf_control, args.perf_ack,
                                                args.perf_timeout_ms, args.repeats);
    }
    std::vector<double> times(args.repeats);
    for (std::size_t r = 0; r < args.repeats; ++r) {
        times[r] = run_once();
        if (csv.is_open()) {
            csv << args.only << ',' << args.search.threads << ',' << args.queries << ','
                << args.batch << ',' << args.search.k << ',' << args.search.nprobe << ',' << args.search.grain << ','
                << (args.search.simd ? "on" : "off") << ',' << args.query_order << ',' << r + 1 << ','
                << times[r] << ',' << args.queries * 1000.0 / times[r] << ',' << recall << ",PASS\n";
        }
        if (batches.is_open()) {
            for (std::size_t b = 0; b < samples.size(); ++b) {
                batches << args.only << ',' << (args.search.simd ? "on" : "off") << ',' << args.query_order << ','
                        << args.search.threads << ',' << r + 1 << ',' << b << ',' << samples[b].begin << ','
                        << samples[b].count << ',' << samples[b].ms << '\n';
            }
        }
    }
    if (perf) perf->save_log(args.perf_log);
    if (csv.is_open()) csv.close();
    if (batches.is_open()) batches.close();
    std::sort(times.begin(), times.end());
    const double median = (times[(times.size() - 1) / 2] + times[times.size() / 2]) / 2;
    std::cout << "correctness=PASS recall@" << args.search.k << '=' << recall << '\n'
              << "time_ms[min/median/max]=" << times.front() << '/' << median << '/' << times.back()
              << " qps=" << args.queries * 1000.0 / median << '\n';
    return 0;
}

int main(int argc, char** argv) {
    try { return run(argc, argv); }
    catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
