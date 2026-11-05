#include "ivf_search.h"

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

template <bool Simd>
void search_query(const IVFIndex& index, const float* query,
                  const SearchOptions& options, Neighbor* output) {
    // All versions use the supplied scalar center selection and tie ordering.
    const auto lists = select_lists(index, query, options.nprobe);
    TopK best(options.k);
    for (const auto list : lists) {
        for (std::size_t p = index.list_ptr[list]; p < index.list_ptr[list + 1]; ++p) {
            best.add({distance<Simd>(query, index.vector(p), index.dim), index.ids[p]});
        }
    }
    best.finish(output);
}

template <bool Simd>
void search_query_parallel(const IVFIndex& index, const float* queries, std::size_t count,
                           const SearchOptions& options, Neighbor* output) {
    std::vector<std::exception_ptr> failures(count);
    #pragma omp parallel for num_threads(options.threads) schedule(static)
    for (std::size_t q = 0; q < count; ++q) {
        try {
            search_query<Simd>(index, queries + q * index.dim, options, output + q * options.k);
        } catch (...) {
            // Exceptions must stay inside their OpenMP region until the team joins.
            failures[q] = std::current_exception();
        }
    }
    rethrow_first(failures);
}

struct Block {
    std::size_t begin, end;
};

template <bool Simd>
void search_query_tasks(const IVFIndex& index, const float* query,
                        const SearchOptions& options, Neighbor* output) {
    const auto lists = select_lists(index, query, options.nprobe);
    std::vector<Block> blocks;
    for (const auto list : lists) {
        const auto end = index.list_ptr[list + 1];
        for (auto begin = index.list_ptr[list]; begin < end;) {
            // Split even a single long list; these disjoint intervals cover it once.
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

    // The parent query owns all buffers. Child b alone writes partial[b*k:(b+1)*k].
    #pragma omp taskgroup
    {
        for (std::size_t b = 0; b < blocks.size(); ++b) {
            #pragma omp task firstprivate(b, query, k) shared(index, blocks, partial, failures)
            {
                try {
                    TopK best(k);
                    const auto block = blocks[b];
                    for (auto p = block.begin; p < block.end; ++p) {
                        best.add({distance<Simd>(query, index.vector(p), index.dim), index.ids[p]});
                    }
                    best.finish(partial.data() + b * k);
                } catch (...) {
                    failures[b] = std::current_exception();
                }
            }
        }
    }
    // The taskgroup waits before reading results, rethrowing, or releasing buffers.
    rethrow_first(failures);
    TopK best(k);
    for (const auto& candidate : partial) {
        if (candidate.id >= 0) best.add(candidate);
    }
    best.finish(output);
}

template <bool Simd>
void search_task_parallel(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    std::vector<std::exception_ptr> failures(count);
    // Exactly one team per batch. Parent queries and all candidate tasks share it.
    #pragma omp parallel num_threads(options.threads)
    {
        #pragma omp single
        {
            for (std::size_t q = 0; q < count; ++q) {
                const auto* query = queries + q * index.dim;
                auto* result = output + q * options.k;
                #pragma omp task firstprivate(q, query, result) shared(index, options, failures)
                {
                    try {
                        search_query_tasks<Simd>(index, query, options, result);
                    } catch (...) {
                        failures[q] = std::current_exception();
                    }
                }
            }
        }
    }
    rethrow_first(failures);
}

}  // namespace

void search_std_thread(const IVFIndex& index, const float* queries, std::size_t count,
                       const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (options.simd) throw std::invalid_argument("std uses the reference scalar distance");
    if (!count) return;
    const auto workers = std::min(count, static_cast<std::size_t>(options.threads));
    std::vector<std::thread> threads;
    std::vector<std::exception_ptr> failures(workers);
    threads.reserve(workers);
    try {
        for (std::size_t t = 0; t < workers; ++t) {
            // Balanced contiguous intervals, including a final short batch.
            const auto begin = t * (count / workers) + std::min(t, count % workers);
            const auto end = begin + count / workers + (t < count % workers);
            threads.emplace_back([&, t, begin, end] {
                try {
                    for (auto q = begin; q < end; ++q) {
                        search_query<false>(index, queries + q * index.dim,
                                            options, output + q * options.k);
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

void search_omp_student_1(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (!count) return;
    if (options.simd) search_query_parallel<true>(index, queries, count, options, output);
    else search_query_parallel<false>(index, queries, count, options, output);
}

void search_omp_student_2(const IVFIndex& index, const float* queries, std::size_t count,
                          const SearchOptions& options, Neighbor* output) {
    validate(index, options);
    if (!count) return;
    if (options.simd) search_task_parallel<true>(index, queries, count, options, output);
    else search_task_parallel<false>(index, queries, count, options, output);
}

}  // namespace ivf
