#include "ivf_search.h"

#include <omp.h>

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>

namespace {

struct Strategy {
    const char* name;
    ivf::SearchFunction search;
    bool simd;
};

const Strategy strategies[]{
    {"std", ivf::search_std_thread, false},
    {"omp1/scalar", ivf::search_omp_student_1, false},
    {"omp1/simd", ivf::search_omp_student_1, true},
    {"omp2/scalar", ivf::search_omp_student_2, false},
    {"omp2/simd", ivf::search_omp_student_2, true},
};

std::size_t cases = 0;

void check_batches(const ivf::IVFIndex& index, const std::vector<float>& queries,
                   ivf::SearchOptions options, std::size_t batch) {
    const auto count = queries.size() / index.dim;
    std::vector<ivf::Neighbor> expected(count * options.k);
    // Independent full scan when probing every list; serial IVF otherwise.
    const auto reference = options.nprobe == index.nlist
        ? ivf::search_exact_serial : ivf::search_ivf_serial;
    reference(index, queries.data(), count, options, expected.data());
    const auto poison = ivf::Neighbor{std::numeric_limits<double>::quiet_NaN(), -2};

    for (const auto& strategy : strategies) {
        options.simd = strategy.simd;
        // Guard both ends of the output; poison detects unwritten result slots.
        std::vector<ivf::Neighbor> guarded(expected.size() + 2, {12345.0, -123});
        auto* output = guarded.data() + 1;
        std::fill_n(output, expected.size(), poison);
        for (std::size_t begin = 0; begin < count; begin += batch) {
            strategy.search(index, queries.data() + begin * index.dim,
                            std::min(batch, count - begin), options, output + begin * options.k);
        }
        try {
            ivf::check_result(std::vector<ivf::Neighbor>(output, output + expected.size()), expected);
            if (guarded.front().id != -123 || guarded.front().distance != 12345.0 ||
                guarded.back().id != -123 || guarded.back().distance != 12345.0) {
                throw std::runtime_error("output buffer overrun");
            }
        } catch (const std::exception& e) {
            throw std::runtime_error(std::string(strategy.name) + " p=" +
                std::to_string(options.threads) + " batch=" + std::to_string(batch) +
                " k=" + std::to_string(options.k) + " nprobe=" +
                std::to_string(options.nprobe) + " grain=" + std::to_string(options.grain) +
                ": " + e.what());
        }
        ++cases;
    }
}

void edge_cases() {
    // Empty first list; ties with scrambled IDs; fewer than k candidates.
    const ivf::IVFIndex index{
        5, 2, 3,
        {0, 0, 3, 5},
        {4, 0, 2, 3, 1},
        {1, 0, 0, 0, 1, 0, 10, 11, 10, 10},
        {99, 99, 0, 0, 10, 10},
    };
    const std::vector<float> queries{0, 0, 10, 10, 99, 99, 1, 0, 10, 11};
    ivf::SearchOptions options;
    for (const int threads : {1, 2, 4, 8}) {
        options.threads = threads;
        for (const std::size_t batch : {1, 3, 8}) {
            for (const std::size_t k : {1, 4, 7}) {
                options.k = k;
                for (const std::size_t nprobe : {1, 3}) {
                    options.nprobe = nprobe;
                    for (const std::size_t grain : {1, 2, 64}) {
                        options.grain = grain;
                        check_batches(index, queries, options, batch);
                    }
                }
            }
        }
    }
    // Zero queries must leave the output untouched, including with null inputs.
    options.nprobe = 1;
    ivf::Neighbor untouched{123, 9};
    for (const auto& strategy : strategies) {
        options.simd = strategy.simd;
        strategy.search(index, nullptr, 0, options, &untouched);
        if (untouched.id != 9 || untouched.distance != 123) {
            throw std::runtime_error("zero-query call wrote output");
        }
    }
}

ivf::IVFIndex random_index(std::size_t dim, std::mt19937& rng) {
    ivf::IVFIndex index;
    index.dim = dim;
    index.nlist = 7;
    // Long lists require splitting; includes empty and very short lists.
    const std::size_t lengths[]{0, 1, 67, 0, 3, 129, 7};
    index.list_ptr.push_back(0);
    for (const auto length : lengths) index.list_ptr.push_back(index.list_ptr.back() + length);
    index.size = index.list_ptr.back();
    index.ids.resize(index.size);
    std::iota(index.ids.begin(), index.ids.end(), 0);
    std::shuffle(index.ids.begin(), index.ids.end(), rng);
    std::uniform_int_distribution<int> value(-127, 127);
    index.vectors.resize(index.size * dim);
    for (auto& x : index.vectors) x = static_cast<float>(value(rng));
    // Exact duplicates across block boundaries exercise deterministic tie-breaking.
    for (std::size_t p = 3; p < index.size; p += 11) {
        std::copy_n(index.vectors.data(), dim, index.vectors.data() + p * dim);
    }
    index.centroids.resize(index.nlist * dim);
    for (auto& x : index.centroids) x = static_cast<float>(value(rng)) * 0.25f;
    return index;
}

void random_cases() {
    std::mt19937 rng(20261105);
    std::uniform_int_distribution<int> value(-127, 127);
    ivf::SearchOptions options;
    for (const std::size_t dim : {1, 3, 17, 128, 129}) {
        const auto index = random_index(dim, rng);
        std::vector<float> queries(9 * dim);
        for (auto& x : queries) x = static_cast<float>(value(rng));
        std::copy_n(index.vectors.data(), dim, queries.data());
        for (const int threads : {1, 4}) {
            options.threads = threads;
            for (const std::size_t batch : {1, 4, 16}) {
                for (const std::size_t nprobe : {1, 3, 7}) {
                    options.nprobe = nprobe;
                    options.k = 10;
                    for (const std::size_t grain : {1, 8, 64, 4096}) {
                        options.grain = grain;
                        check_batches(index, queries, options, batch);
                    }
                }
            }
        }
        // Keep most/all candidates, so merging cannot hide missing non-neighbors.
        options.nprobe = index.nlist;
        options.k = index.size + 3;
        options.grain = 8;
        check_batches(index, queries, options, 4);
    }
}

void distance_cases() {
    std::mt19937 rng(17);
    std::uniform_int_distribution<int> value(-255, 255);
    std::vector<float> a(262), b(262);
    for (auto& x : a) x = static_cast<float>(value(rng));
    for (auto& x : b) x = static_cast<float>(value(rng));
    for (const std::size_t dim : {0, 1, 2, 3, 7, 17, 128, 129, 257}) {
        // Offset pointers exercise unaligned input and dimensions with SIMD tails.
        const auto expected = ivf::l2_distance_scalar(a.data() + 1, b.data() + 3, dim);
        if (ivf::l2_distance_simd(a.data() + 1, b.data() + 3, dim) != expected) {
            throw std::runtime_error("SIMD integer-coordinate distance mismatch");
        }
    }
}

}  // namespace

int main() {
    try {
        omp_set_dynamic(0);
        distance_cases();
        edge_cases();
        random_cases();
        std::cout << "PASS: " << cases << " student strategy configurations; SIMD distances, "
                     "threads 1/2/4/8, batches, ties, empty/long lists, padding, full scan\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
