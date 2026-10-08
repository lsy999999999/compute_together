#define main lab_main
#include "../csr_spmv_lab.cpp"
#undef main

static int checks = 0;

static void verify(const std::vector<int>& lengths, unsigned seed) {
    CsrMatrix matrix;
    matrix.rows = static_cast<int>(lengths.size());
    matrix.cols = 257;
    matrix.row_ptr.push_back(0);
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> value(-1.0, 1.0);
    for (int length : lengths) {
        matrix.row_ptr.push_back(matrix.row_ptr.back() + length);
        for (int i = 0; i < length; ++i) {
            matrix.col_idx.push_back(rng() % matrix.cols);
            matrix.values.push_back(value(rng));
        }
    }
    using Fn = void (*)(const CsrMatrix&, const std::vector<double>&, std::vector<double>&);
    for (int threads : {1, 2, 3, 4, 8, 16}) {
#ifdef _OPENMP
        omp_set_num_threads(threads);
#endif
        std::vector<double> y(lengths.size()), expected(lengths.size());
        for (int call = 0; call < 3; ++call) {
            const auto x = make_vector(matrix.cols, seed + call);
            spmv_serial(matrix, x, expected);
            for (Fn strategy : {spmv_omp_student_1, spmv_omp_student_2}) {
                std::fill(y.begin(), y.end(), std::numeric_limits<double>::quiet_NaN());
                strategy(matrix, x, y);
                for (double v : y) {
                    if (!std::isfinite(v)) throw std::runtime_error("unwritten output row");
                }
                if (!check_result(expected, y)) throw std::runtime_error("incorrect output");
                ++checks;
            }
        }
    }
}

int main() {
    verify({}, 1);
    verify({0}, 2);
    verify({1}, 3);
    verify({100000}, 4);
    verify({0, 0, 1, 0, 0}, 5);
    verify({0, 0, 100000, 0, 0}, 6);
    verify({0, 3, 0, 0, 5, 0, 1, 0, 0}, 7);
    verify({1, 1, 1, 1, 1, 1, 1}, 8);
    verify(std::vector<int>(10000, 0), 9);
    std::mt19937 rng(98765);
    for (int trial = 0; trial < 200; ++trial) {
        std::vector<int> lengths(1 + rng() % 257);
        for (int& length : lengths) {
            const unsigned kind = rng() % 10;
            length = kind < 4 ? 0 : (kind < 9 ? rng() % 33 : rng() % 20001);
        }
        verify(lengths, rng());
    }
    std::cout << checks << " correctness checks passed.\n";
}
