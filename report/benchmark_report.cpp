#define main lab_main
#include "../csr_spmv_lab.cpp"
#undef main
#include <functional>

int main(int argc, char** argv) {
    const Options options = parse_options(argc, argv);
#ifdef _OPENMP
    omp_set_num_threads(options.threads);
#endif
    const auto matrix = make_skewed_matrix(options);
    const auto x = make_vector(options.cols, options.seed);
    std::vector<double> reference(options.rows), output(options.rows);
    spmv_serial(matrix, x, reference);
    using Kernel = std::function<void(std::vector<double>&)>;
    const std::vector<std::pair<std::string, Kernel>> strategies = {
        {"serial", [&](auto& y) { spmv_serial(matrix, x, y); }},
        {"std_thread", [&](auto& y) { spmv_std_thread(matrix, x, y, options.threads); }},
        {"row_static", [&](auto& y) { spmv_omp_row_static(matrix, x, y); }},
        {"row_dynamic", [&](auto& y) { spmv_omp_row_dynamic(matrix, x, y); }},
        {"student1", [&](auto& y) { spmv_omp_student_1(matrix, x, y); }},
        {"student2", [&](auto& y) { spmv_omp_student_2(matrix, x, y); }},
    };
    std::vector<int> order(strategies.size());
    std::iota(order.begin(), order.end(), 0);
    std::mt19937 rng(20261005);
    std::cout << "strategy,trial,ms\n";
    for (int trial = 0; trial < 10; ++trial) {
        std::shuffle(order.begin(), order.end(), rng);
        for (int index : order) {
            std::fill(output.begin(), output.end(), std::numeric_limits<double>::quiet_NaN());
            const double ms = benchmark_ms(strategies[index].second, reference,
                                            output, options.repeats);
            for (double value : output) {
                if (!std::isfinite(value)) throw std::runtime_error("unwritten output row");
            }
            if (!check_result(reference, output)) throw std::runtime_error("incorrect output");
            std::cout << strategies[index].first << ',' << trial << ','
                      << std::fixed << std::setprecision(6) << ms << '\n';
        }
    }
}
