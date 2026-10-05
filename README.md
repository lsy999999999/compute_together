# OpenMP CSR SpMV 并行策略实验

这是一个自包含的 C++ 参考代码，实验对象是“少数行特别长”的 skewed CSR 矩阵。
矩阵和输入向量都由固定随机种子生成，因此不同并行策略可以在同一输入上比较。

代码包含：

- naive 串行 CSR SpMV；
- `std::thread` 的连续行分块并行实现；
- 四个 OpenMP 策略：按行 static、按行 dynamic(128)、
  静态 NNZ 切块加 SIMD、动态 NNZ 小块加 SIMD；
- 结果正确性校验器；
- 简单的重复计时和命令行参数。

## 编译运行

```bash
g++ -O2 -std=c++17 -fopenmp -pthread csr_spmv_lab.cpp -o csr_spmv_lab
./csr_spmv_lab --threads 8 --repeats 10
```

如果省略 `-fopenmp`，OpenMP 函数将按串行方式执行。

NNZ 策略的对照实验、消融测试和复现命令见
[experiments/README.md](experiments/README.md)。

## 实验入口
请实现
`spmv_omp_student_1`, `spmv_omp_student_2`两种不同的自定义openmp并行策略，并分析两种策略性能差别原因。

如果有其他你觉得有趣有价值的并行策略，也可以继续注册`spmv_omp_student_3`等函数，但`spmv_omp_student`的函数数量不得超过5个（上限为`spmv_omp_student_5`），超过5个的部分将不会被检查。**作业成绩与额外注册函数的数量无关**。

每次实现都会经过同一个 `check_result`，浮点误差允许绝对误差和相对误差各
`1e-10`。可以修改命令行参数来改变 skew 程度，例如：

```bash
./csr_spmv_lab --rows 20000 --cols 200000 \
  --normal-nnz 16 --long-rows 16 --long-nnz 80000 \
  --threads 16 --repeats 20
```
