#include "ivf_search.h"
#include "ivf_profile.h"

#include <omp.h>

#include <algorithm>
#include <exception>
#include <stdexcept>
#include <thread>
#include <vector>

namespace ivf {

double l2_distance_simd(const float* a, const float* b, std::size_t dim) {
    double sum = 0;
    #pragma omp simd reduction(+:sum)
    for (std::size_t j = 0; j < dim; ++j) {
        const double delta = double(a[j]) - double(b[j]);
        sum += delta * delta;
    }
    return sum;
}

namespace {

void validate(const IVFIndex& index, const SearchOptions& options) {
    if (!options.k || !options.nprobe || options.nprobe > index.nlist ||
        options.threads <= 0 || !options.grain) {
        throw std::invalid_argument("invalid search options");
    }
}

void rethrow_first(const std::vector<std::exception_ptr>& failures) {
    for (const auto& failure : failures) {
        if (failure) std::rethrow_exception(failure);
    }
}

template <bool Simd>
double distance(const float* query, const float* vector, std::size_t dim) {
    if constexpr (Simd) return l2_distance_simd(query, vector, dim);
    return l2_distance_scalar(query, vector, dim);
}

template <bool Simd, bool Profile>
void search_query(const IVFIndex& index, const float* query,
                  const SearchOptions& options, Neighbor* output,
                  std::size_t q, std::size_t thread) {
    const auto select_start = profile_now<Profile>();
    const auto lists = select_lists(index, query, options.nprobe);
    if constexpr (Profile) options.statistics->queries[q].select_ms = elapsed_ms(select_start);
    const auto scan_start = profile_now<Profile>();
    TopK best(options.k);
    std::size_t candidates = 0;
    for (const auto list : lists) {
        for (std::size_t p = index.list_ptr[list]; p < index.list_ptr[list + 1]; ++p) {
            best.add({distance<Simd>(query, index.vector(p), index.dim), index.ids[p]});
        }
        if constexpr (Profile) candidates += index.list_ptr[list + 1] - index.list_ptr[list];
    }
    best.finish(output);
    if constexpr (Profile) {
        auto& stats = *options.statistics;
        stats.queries[q].scan_topk_ms = elapsed_ms(scan_start);
        stats.queries[q].candidates = candidates;
        record_work(stats.threads[thread], candidates, 0, 1);
    }
}

template <bool Simd, bool Profile>
void search_query_parallel(const IVFIndex& index, const float* queries, std::size_t count,
                           const SearchOptions& options, Neighbor* output) {
    if constexpr (Profile) options.statistics->reset(count, options.threads);
    std::vector<std::exception_ptr> failures(count);
    #pragma omp parallel num_threads(options.threads)
    {
        if constexpr (Profile) {
            #pragma omp single nowait
            { options.statistics->actual_threads = omp_get_num_threads(); }
        }
        #pragma omp for schedule(static)
        for (std::size_t q = 0; q < count; ++q) {
            try {
                std::size_t thread = 0;
                if constexpr (Profile) thread = static_cast<std::size_t>(omp_get_thread_num());
                search_query<Simd, Profile>(index, queries + q * index.dim, options,
                                            output + q * options.k, q, thread);
            } catch (...) {
                failures[q] = std::current_exception();
            }
        }
    }
    rethrow_first(failures);
}

struct Block { std::size_t begin, end; };

template <bool Simd, bool Profile>
void search_query_tasks(const IVFIndex& index, const float* query,
                        const SearchOptions& options, Neighbor* output, std::size_t q) {
    const auto select_start = profile_now<Profile>();
    const auto lists = select_lists(index, query, options.nprobe);
    if constexpr (Profile) options.statistics->queries[q].select_ms = elapsed_ms(select_start);
    const auto partition_start = profile_now<Profile>();
    std::vector<Block> blocks;
    std::size_t candidates = 0;
    for (const auto list : lists) {
        const auto end = index.list_ptr[list + 1];
        if constexpr (Profile) candidates += end - index.list_ptr[list];
        for (auto begin = index.list_ptr[list]; begin < end;) {
            const auto next = begin + std::min(options.grain, end - begin);
            blocks.push_back({begin, next});
            begin = next;
        }
    }
    const auto k = options.k;
    if (blocks.size() > std::vector<Neighbor>().max_size() / k) {
        throw std::length_error("local Top-k workspace too large");
    }
    std::vector<Neighbor> partial(blocks.size() * k);
    std::vector<std::exception_ptr> failures(blocks.size());
    if constexpr (Profile) {
        auto& stats = options.statistics->queries[q];
        stats.partition_ms = elapsed_ms(partition_start);
        stats.candidates = candidates;
        stats.candidate_tasks = blocks.size();
        stats.local_result_bytes = partial.capacity() * sizeof(Neighbor);
        stats.descriptor_bytes = blocks.capacity() * sizeof(Block);
        stats.exception_bytes = failures.capacity() * sizeof(std::exception_ptr);
        stats.child_heap_upper_bound_bytes = std::min(blocks.size(), std::size_t(options.threads))
            * k * sizeof(Neighbor);
    }
    const auto task_start = profile_now<Profile>();
    // The parent owns the buffers. Each child writes one disjoint result slice.
    #pragma omp taskgroup
    {
        for (std::size_t b = 0; b < blocks.size(); ++b) {
            #pragma omp task firstprivate(b, query, k, q) shared(index, blocks, partial, failures, options)
            {
                try {
                    TopK best(k);
                    const auto block = blocks[b];
                    for (auto p = block.begin; p < block.end; ++p) {
                        best.add({distance<Simd>(query, index.vector(p), index.dim), index.ids[p]});
                    }
                    best.finish(partial.data() + b * k);
                    if constexpr (Profile) {
                        record_work(options.statistics->threads[omp_get_thread_num()],
                                    block.end - block.begin, 1, 0);
                    }
                } catch (...) {
                    failures[b] = std::current_exception();
                }
            }
        }
    }
    if constexpr (Profile) options.statistics->queries[q].taskgroup_ms = elapsed_ms(task_start);
    rethrow_first(failures);
    const auto merge_start = profile_now<Profile>();
    TopK best(k);
    for (const auto& candidate : partial) {
        if (candidate.id >= 0) best.add(candidate);
    }
    best.finish(output);
    if constexpr (Profile) {
        options.statistics->queries[q].merge_ms = elapsed_ms(merge_start);
        record_work(options.statistics->threads[omp_get_thread_num()], 0, 0, 1);
    }
}

template <bool Simd, bool Profile>
void search_task_parallel(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    if constexpr (Profile) options.statistics->reset(count, options.threads);
    std::vector<std::exception_ptr> failures(count);
    // One team per batch, including parent-query tasks and all their children.
    #pragma omp parallel num_threads(options.threads)
    {
        #pragma omp single
        {
            if constexpr (Profile) options.statistics->actual_threads = omp_get_num_threads();
            for (std::size_t q = 0; q < count; ++q) {
                const auto* query = queries + q * index.dim;
                auto* result = output + q * options.k;
                #pragma omp task firstprivate(q, query, result) shared(index, options, failures)
                {
                    try {
                        search_query_tasks<Simd, Profile>(index, query, options, result, q);
                    } catch (...) {
                        failures[q] = std::current_exception();
                    }
                }
            }
        }
    }
    rethrow_first(failures);
}

template <bool Profile>
void search_threads(const IVFIndex& index, const float* queries, std::size_t count,
                     const SearchOptions& options, Neighbor* output) {
    const auto workers = std::min(count, static_cast<std::size_t>(options.threads));
    if constexpr (Profile) {
        options.statistics->reset(count, options.threads);
        options.statistics->actual_threads = static_cast<int>(workers);
    }
    std::vector<std::thread> threads;
    std::vector<std::exception_ptr> failures(workers);
    threads.reserve(workers);
    try {
        for (std::size_t t = 0; t < workers; ++t) {
            const auto begin = t * (count / workers) + std::min(t, count % workers);
            const auto end = begin + count / workers + (t < count % workers);
            threads.emplace_back([&, t, begin, end] {
                try {
                    if (!options.pin_cpus.empty()) {
                        pin_current_thread(options.pin_cpus[t % options.pin_cpus.size()]);
                    }
                    for (auto q = begin; q < end; ++q) {
                        search_query<false, Profile>(index, queries + q * index.dim,
                                                      options, output + q * options.k, q, t);
                    }
                } catch (...) {
                    failures[t] = std::current_exception();
                }
            });
        }
    } catch (...) {
        for (auto& thread : threads) thread.join();
        throw;
    }
    for (auto& thread : threads) thread.join();
    rethrow_first(failures);
}

template <bool Profile>
void dispatch_omp1(const IVFIndex& index, const float* queries, std::size_t count,
                   const SearchOptions& options, Neighbor* output) {
    if (options.simd) search_query_parallel<true, Profile>(index, queries, count, options, output);
    else search_query_parallel<false, Profile>(index, queries, count, options, output);
}

template <bool Profile>
void dispatch_omp2(const IVFIndex& index, const float* queries, std::size_t count,
                   const SearchOptions& options, Neighbor* output) {
    if (options.simd) search_task_parallel<true, Profile>(index, queries, count, options, output);
    else search_task_parallel<false, Profile>(index, queries, count, options, output);
}

}  // namespace

void search_serial_diagnostics(const IVFIndex& index, const float* queries, std::size_t count,
                                const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (!options.statistics) throw std::invalid_argument("serial diagnostics require statistics");
    options.statistics->reset(count, 1);
    options.statistics->actual_threads = count ? 1 : 0;
    for (std::size_t q = 0; q < count; ++q) {
        search_query<false, true>(index, queries + q * index.dim, options, output + q * options.k, q, 0);
    }
}

void search_std_thread(const IVFIndex& index, const float* queries, std::size_t count,
                       const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (options.simd) throw std::invalid_argument("std uses the reference scalar distance");
    if (!count) return;
    if (options.statistics) search_threads<true>(index, queries, count, options, output);
    else search_threads<false>(index, queries, count, options, output);
}

void search_omp_student_1(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (!count) return;
    if (options.statistics) dispatch_omp1<true>(index, queries, count, options, output);
    else dispatch_omp1<false>(index, queries, count, options, output);
}

void search_omp_student_2(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (!count) return;
    if (options.statistics) dispatch_omp2<true>(index, queries, count, options, output);
    else dispatch_omp2<false>(index, queries, count, options, output);
}

}  // namespace ivf
