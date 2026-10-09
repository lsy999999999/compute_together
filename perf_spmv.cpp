// Single-strategy perf measurement driver; includes the exact submitted algorithms.
// Usage: ./perf_spmv student1 --threads 8 --repeats 10000
#define main original_spmv_main
#include "csr_spmv_lab.cpp"
#undef main

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            std::cerr << "Usage: " << argv[0]
                      << " {serial|std_thread|student1|student2|student3|student4} [options]\n";
            return 1;
        }
        const std::string strategy(argv[1]);
        std::vector<char*> args{argv[0]};
        for (int i = 2; i < argc; ++i) args.push_back(argv[i]);
        const Options o = parse_options(static_cast<int>(args.size()), args.data());
#ifdef _OPENMP
        omp_set_dynamic(0);
        omp_set_num_threads(o.threads);
#endif
        const auto matrix = make_skewed_matrix(o);
        const auto x = make_vector(o.cols, o.seed);
        std::vector<double> reference(o.rows), output(o.rows);
        spmv_serial(matrix, x, reference);
        auto run = [&](std::vector<double>& y) {
            if (strategy == "serial") spmv_serial(matrix, x, y);
            else if (strategy == "std_thread") spmv_std_thread(matrix, x, y, o.threads);
            else if (strategy == "student1") spmv_omp_student_1(matrix, x, y);
            else if (strategy == "student2") spmv_omp_student_2(matrix, x, y);
            else if (strategy == "student3") spmv_omp_student_3(matrix, x, y);
            else if (strategy == "student4") spmv_omp_student_4(matrix, x, y);
            else throw std::invalid_argument("unknown strategy: " + strategy);
        };
        const double ms = benchmark_ms(run, reference, output, o.repeats);
        for (double y : output) {
            if (!std::isfinite(y)) throw std::runtime_error("unwritten output row");
        }
        std::cout << strategy << "," << o.threads << "," << o.repeats << ","
                  << std::fixed << std::setprecision(6) << ms << " ms/call\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
