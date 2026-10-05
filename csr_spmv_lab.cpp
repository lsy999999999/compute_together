#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifdef _OPENMP
#include <omp.h>
#endif

struct CsrMatrix {
    int rows = 0;
    int cols = 0;
    std::vector<int> row_ptr;
    std::vector<int> col_idx;
    std::vector<double> values;
};

struct Options {
    int rows = 10000;
    int cols = 100000;
    int normal_nnz = 32;
    int long_rows = 32;
    int long_nnz = 20000;
    int threads = 8;
    int repeats = 10;
    unsigned seed = 20260926u;
};

static void usage(const char* program) {
    std::cout
        << "Usage: " << program << " [options]\n"
        << "  --rows N          number of rows, default 10000\n"
        << "  --cols N          number of columns, default 100000\n"
        << "  --normal-nnz N    nnz per ordinary row, default 32\n"
        << "  --long-rows N     number of skewed long rows, default 32\n"
        << "  --long-nnz N      nnz per long row, default 20000\n"
        << "  --threads N       std::thread/OpenMP threads, default 8\n"
        << "  --repeats N       timed repetitions, default 10\n"
        << "  --seed N          fixed random seed, default 20260926\n";
}

static int read_int_arg(int argc, char** argv, int& i, const std::string& name) {
    if (i + 1 >= argc) {
        throw std::invalid_argument("missing value for " + name);
    }
    return std::stoi(argv[++i]);
}

static Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            usage(argv[0]);
            std::exit(0);
        } else if (arg == "--rows") {
            options.rows = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--cols") {
            options.cols = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--normal-nnz") {
            options.normal_nnz = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--long-rows") {
            options.long_rows = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--long-nnz") {
            options.long_nnz = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--threads") {
            options.threads = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--repeats") {
            options.repeats = read_int_arg(argc, argv, i, arg);
        } else if (arg == "--seed") {
            options.seed = static_cast<unsigned>(read_int_arg(argc, argv, i, arg));
        } else {
            throw std::invalid_argument("unknown option: " + arg);
        }
    }

    if (options.rows <= 0 || options.cols <= 0 || options.normal_nnz < 0 ||
        options.long_rows < 0 || options.long_rows > options.rows ||
        options.long_nnz < 0 || options.long_nnz > options.cols ||
        options.threads <= 0 || options.repeats <= 0) {
        throw std::invalid_argument("invalid option value");
    }
    return options;
}

static CsrMatrix make_skewed_matrix(const Options& options) {
    CsrMatrix matrix;
    matrix.rows = options.rows;
    matrix.cols = options.cols;
    matrix.row_ptr.resize(static_cast<std::size_t>(matrix.rows) + 1, 0);

    std::mt19937 rng(options.seed);
    std::vector<int> row_ids(matrix.rows);
    std::iota(row_ids.begin(), row_ids.end(), 0);
    std::shuffle(row_ids.begin(), row_ids.end(), rng);
    std::vector<char> is_long(matrix.rows, false);
    for (int i = 0; i < options.long_rows; ++i) {
        is_long[row_ids[i]] = true;
    }

    std::uniform_real_distribution<double> value_dist(-1.0, 1.0);
    std::uniform_int_distribution<int> column_dist(0, options.cols - 1);

    for (int row = 0; row < matrix.rows; ++row) {
        const int nnz = is_long[row] ? options.long_nnz : options.normal_nnz;
        matrix.row_ptr[row + 1] = matrix.row_ptr[row] + nnz;
        for (int k = 0; k < nnz; ++k) {
            matrix.col_idx.push_back(column_dist(rng));
            matrix.values.push_back(value_dist(rng));
        }
    }
    return matrix;
}


static std::vector<double> make_vector(int size, unsigned seed) {
    std::mt19937 rng(seed ^ 0x9e3779b9u);
    std::uniform_real_distribution<double> dist(-1.0, 1.0);
    std::vector<double> x(size);
    for (double& value : x) {
        value = dist(rng);
    }
    return x;
}

static void spmv_serial(const CsrMatrix& matrix, const std::vector<double>& x,
                        std::vector<double>& y) {
    for (int row = 0; row < matrix.rows; ++row) {
        double sum = 0.0;
        for (int p = matrix.row_ptr[row]; p < matrix.row_ptr[row + 1]; ++p) {
            sum += matrix.values[p] * x[matrix.col_idx[p]];
        }
        y[row] = sum;
    }
}

static void spmv_std_thread(const CsrMatrix& matrix, const std::vector<double>& x,
                            std::vector<double>& y, int thread_count) {
    const int workers = std::max(1, std::min(thread_count, matrix.rows));
    std::vector<std::thread> threads;
    threads.reserve(workers);

    for (int worker = 0; worker < workers; ++worker) {
        const int begin = matrix.rows * worker / workers;
        const int end = matrix.rows * (worker + 1) / workers;
        threads.emplace_back([&, begin, end]() {
            for (int row = begin; row < end; ++row) {
                double sum = 0.0;
                for (int p = matrix.row_ptr[row]; p < matrix.row_ptr[row + 1]; ++p) {
                    sum += matrix.values[p] * x[matrix.col_idx[p]];
                }
                y[row] = sum;
            }
        });
    }
    for (std::thread& thread : threads) {
        thread.join();
    }
}

// TODO 1: replace the fallback with an OpenMP parallel implementation.
static void spmv_omp_student_1(
    const CsrMatrix& matrix,
    const std::vector<double>& x,
    std::vector<double>& y) {

#pragma omp parallel for schedule(static)
    for (int row = 0; row < matrix.rows; ++row) {
        double sum = 0.0;

        for (int p = matrix.row_ptr[row];
             p < matrix.row_ptr[row + 1];
             ++p) {

            sum += matrix.values[p] * x[matrix.col_idx[p]];
        }

        y[row] = sum;
    }
}

// TODO 2: replace the fallback with another OpenMP implementation.
static void spmv_omp_student_2(
    const CsrMatrix& matrix,
    const std::vector<double>& x,
    std::vector<double>& y) {

#pragma omp parallel for schedule(dynamic, 128)
//这里先试过runtime，然后再做的这些，所以确认128应该是一个比较好的点
    for (int row = 0; row < matrix.rows; ++row) {
        double sum = 0.0;

        for (int p = matrix.row_ptr[row];
             p < matrix.row_ptr[row + 1];
             ++p) {

            sum += matrix.values[p] * x[matrix.col_idx[p]];
        }

        y[row] = sum;
    }
}

#ifdef _OPENMP
// A contiguous NNZ block can cut at most two rows.
// Padding reduces false sharing between blocks' partial sums.
struct alignas(64) NnzPartialRows {
    int rows[2] = {-1, -1};
    double sums[2] = {0.0, 0.0};
};

static void spmv_nnz_block(const CsrMatrix& matrix, const std::vector<double>& x,
                           std::vector<double>& y, int block, int blocks,
                           NnzPartialRows& partial) {
    const long long total_nnz = matrix.row_ptr.back();
    const int begin = total_nnz * block / blocks;
    const int end = total_nnz * (block + 1) / blocks;

    // upper_bound skips repeated offsets from empty rows. The outer blocks
    // also cover leading and trailing empty rows.
    const int first_row = block == 0 ? 0 : static_cast<int>(
        std::upper_bound(matrix.row_ptr.begin(), matrix.row_ptr.end(), begin)
        - matrix.row_ptr.begin() - 1);
    const int end_row = block == blocks - 1 ? matrix.rows : static_cast<int>(
        std::upper_bound(matrix.row_ptr.begin(), matrix.row_ptr.end(), end)
        - matrix.row_ptr.begin() - 1);

    auto dot = [&](int first, int last) {
        double sum = 0.0;
#pragma omp simd reduction(+:sum)
        for (int p = first; p < last; ++p) {
            sum += matrix.values[p] * x[matrix.col_idx[p]];
        }
        return sum;
    };

    for (int row = first_row; row < end_row; ++row) {
        const int start = std::max(begin, matrix.row_ptr[row]);
        const double sum = dot(start, matrix.row_ptr[row + 1]);
        if (start == matrix.row_ptr[row]) {
            y[row] = sum;
        } else {
            partial.rows[0] = row;
            partial.sums[0] = sum;
        }
    }

    if (end_row < matrix.rows && end > begin && matrix.row_ptr[end_row] < end) {
        partial.rows[1] = end_row;
        partial.sums[1] = dot(std::max(begin, matrix.row_ptr[end_row]), end);
    }
}

static void merge_nnz_partials(const std::vector<NnzPartialRows>& partials,
                               std::vector<double>& y) {
    // Called after the parallel region. Block order is also row order,
    // regardless of the order in which dynamically scheduled blocks finish.
    int previous_row = -1;
    for (const NnzPartialRows& partial : partials) {
        for (int k = 0; k < 2; ++k) {
            const int row = partial.rows[k];
            if (row < 0) {
                continue;
            }
            if (row == previous_row) {
                y[row] += partial.sums[k];
            } else {
                y[row] = partial.sums[k];
            }
            previous_row = row;
        }
    }
}
#endif

static void spmv_omp_student_3(
    const CsrMatrix& matrix,
    const std::vector<double>& x,
    std::vector<double>& y) {
#ifdef _OPENMP
    std::vector<NnzPartialRows> partials(omp_get_max_threads());
#pragma omp parallel
    {
        const int tid = omp_get_thread_num();
        spmv_nnz_block(matrix, x, y, tid, omp_get_num_threads(), partials[tid]);
    }
    merge_nnz_partials(partials, y);
#else
    spmv_serial(matrix, x, y);
#endif
}

static void spmv_omp_student_4(
    const CsrMatrix& matrix,
    const std::vector<double>& x,
    std::vector<double>& y) {
#ifdef _OPENMP
    // A few blocks per worker balance scheduling flexibility against overhead.
    const long long total_nnz = matrix.row_ptr.back();
    const int blocks = static_cast<int>(std::max(1LL, std::min(total_nnz,
        4LL * omp_get_max_threads())));
    std::vector<NnzPartialRows> partials(blocks);
#pragma omp parallel for schedule(dynamic, 1)
    for (int block = 0; block < blocks; ++block) {
        spmv_nnz_block(matrix, x, y, block, blocks, partials[block]);
    }
    merge_nnz_partials(partials, y);
#else
    spmv_serial(matrix, x, y);
#endif
}


static bool check_result(const std::vector<double>& expected,
                         const std::vector<double>& actual,
                         double abs_tol = 1e-10, double rel_tol = 1e-10) {
    if (expected.size() != actual.size()) {
        return false;
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
        const double error = std::abs(expected[i] - actual[i]);
        const double scale = std::max(1.0, std::abs(expected[i]));
        if (error > abs_tol + rel_tol * scale) {
            std::cerr << "mismatch at row " << i << ": expected=" << std::setprecision(17)
                      << expected[i] << ", actual=" << actual[i] << ", error=" << error
                      << '\n';
            return false;
        }
    }
    return true;
}

template <typename Spmv>
static double benchmark_ms(Spmv&& spmv, const std::vector<double>& reference,
                           std::vector<double>& output, int repeats) {
    spmv(output);
    if (!check_result(reference, output)) {
        throw std::runtime_error("correctness check failed");
    }

    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < repeats; ++i) {
        spmv(output);
    }
    const auto stop = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(stop - start).count() / repeats;
}

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        const CsrMatrix matrix = make_skewed_matrix(options);
        const std::vector<double> x = make_vector(options.cols, options.seed);
        const std::size_t nnz = matrix.values.size();
        const std::vector<double> zero(matrix.rows, 0.0);
        std::vector<double> reference = zero;
        std::vector<double> output = zero;

        spmv_serial(matrix, x, reference);

        std::cout << "CSR SpMV skewed-matrix experiment\n"
                  << "rows=" << matrix.rows << ", cols=" << matrix.cols
                  << ", nnz=" << nnz << ", long_rows=" << options.long_rows
                  << ", long_nnz=" << options.long_nnz << ", seed=" << options.seed
                  << ", requested_threads=" << options.threads << '\n';
#ifdef _OPENMP
        std::cout << "OpenMP enabled, _OPENMP=" << _OPENMP << '\n';
        omp_set_num_threads(options.threads);
#else
        std::cout << "OpenMP disabled: compile with -fopenmp to enable it.\n";
#endif

        const double serial_ms = benchmark_ms(
            [&](std::vector<double>& y) { spmv_serial(matrix, x, y); },
            reference, output, options.repeats);
        const double thread_ms = benchmark_ms(
            [&](std::vector<double>& y) {
                spmv_std_thread(matrix, x, y, options.threads);
            },
            reference, output, options.repeats);
        const double openmp_1_ms = benchmark_ms(
            [&](std::vector<double>& y) {
                spmv_omp_student_1(matrix, x, y);
            },
            reference, output, options.repeats);
        const double openmp_2_ms = benchmark_ms(
            [&](std::vector<double>& y) {
                spmv_omp_student_2(matrix, x, y);
            },
            reference, output, options.repeats);
        const double openmp_3_ms = benchmark_ms(
            [&](std::vector<double>& y) {
            spmv_omp_student_3(matrix, x, y);
            },
            reference, output, options.repeats);
        const double openmp_4_ms = benchmark_ms(
            [&](std::vector<double>& y) {
                spmv_omp_student_4(matrix, x, y);
            },
            reference, output, options.repeats);

        std::cout << std::fixed << std::setprecision(3)
                  << "serial                  " << serial_ms << " ms\n"
                  << "std::thread             " << thread_ms << " ms\n"
                  << "OpenMP 1 (TODO)   " << openmp_1_ms << " ms\n"
                  << "OpenMP 2 (TODO)  " << openmp_2_ms << " ms\n"
                  << "OpenMP NNZ-split SIMD   " << openmp_3_ms << " ms\n"
                  << "OpenMP 4 NNZ-dynamic    " << openmp_4_ms << " ms\n"
                  << "All correctness checks passed.\n";
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        usage(argv[0]);
        return 1;
    }
    return 0;
}
