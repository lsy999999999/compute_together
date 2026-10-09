#define main lab_main
#include "../csr_spmv_lab.cpp"
#undef main

template <int BlocksPerWorker, bool Dynamic>
static void spmv_nnz_blocks(const CsrMatrix& matrix,
                            const std::vector<double>& x,
                            std::vector<double>& y) {
#ifdef _OPENMP
    const long long nnz = matrix.row_ptr.back();
    const int blocks = static_cast<int>(std::max(1LL, std::min(nnz,
        1LL * omp_get_max_threads() * BlocksPerWorker)));
    std::vector<NnzPartialRows> partials(blocks);

    auto compute = [&](int block) {
        spmv_nnz_block(matrix, x, y, block, blocks, partials[block]);
    };

    if constexpr (Dynamic) {
#pragma omp parallel for schedule(dynamic, 1)
        for (int block = 0; block < blocks; ++block) {
            compute(block);
        }
    } else {
#pragma omp parallel for schedule(static)
        for (int block = 0; block < blocks; ++block) {
            compute(block);
        }
    }

    merge_nnz_partials(partials, y);
#else
    spmv_serial(matrix, x, y);
#endif
}

#ifndef NNZ_SCHEDULE_BENCHMARK_LIBRARY
int main(int argc, char** argv) {
    const Options o = parse_options(argc, argv);
#ifdef _OPENMP
    omp_set_num_threads(o.threads);
#endif
    const auto matrix = make_skewed_matrix(o);
    const auto x = make_vector(o.cols, o.seed);
    std::vector<double> reference(o.rows), output(o.rows);
    spmv_serial(matrix, x, reference);
    using Fn = void (*)(const CsrMatrix&, const std::vector<double>&, std::vector<double>&);
    const std::vector<Fn> functions = {spmv_omp_student_3, spmv_omp_student_4,
        spmv_omp_student_1, spmv_nnz_blocks<4, false>, spmv_nnz_blocks<2, true>,
        spmv_omp_student_2, spmv_nnz_blocks<8, true>, spmv_nnz_blocks<16, true>};
    const std::vector<std::string> names = {"student3", "student4", "student1",
        "static_blocks4", "dynamic_blocks2", "student2", "dynamic_blocks8",
        "dynamic_blocks16"};
    std::vector<int> order(functions.size());
    std::iota(order.begin(), order.end(), 0);
    std::mt19937 rng(20261005);
    std::cout << "strategy,trial,ms\n";
    for (int trial = 0; trial < 10; ++trial) {
        std::shuffle(order.begin(), order.end(), rng);
        for (int i : order) {
            std::fill(output.begin(), output.end(), std::numeric_limits<double>::quiet_NaN());
            const double time = benchmark_ms([&](auto& y) {functions[i](matrix, x, y);},
                                             reference, output, o.repeats);
            for (double v : output) {
                if (!std::isfinite(v)) throw std::runtime_error("unwritten output row");
            }
            if (!check_result(reference, output)) throw std::runtime_error("incorrect output");
            std::cout << names[i] << ',' << trial << ',' << std::fixed
                      << std::setprecision(6) << time << '\n';
        }
    }
}
#endif
