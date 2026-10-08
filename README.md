# OpenMP CSR SpMV 并行策略实验

这是一个自包含的 C++ 参考代码，实验对象是“少数行特别长”的 skewed CSR 矩阵。
矩阵和输入向量都由固定随机种子生成，因此不同并行策略可以在同一输入上比较。

代码包含：

- naive 串行 CSR SpMV；
- `std::thread` 的连续行分块并行实现；
- 两个对照用按行 OpenMP 基线：`spmv_omp_row_static` (static)、`spmv_omp_row_dynamic` (dynamic,128)；
- 两个正式作业入口：`spmv_omp_student_1`（固定 NNZ 切块 + SIMD）、`spmv_omp_student_2`（动态 NNZ 小块 + SIMD）；
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
课程要求实现 `spmv_omp_student_1` 和 `spmv_omp_student_2` 两种不同的自定义策略。这里将优化效果更好的两种 NNZ 方法放进正式入口，原按行 static/dynamic 保留为对照基线。

**当前映射：** `student1` = 固定 NNZ 切块 + SIMD（原 student3）；`student2` = 动态 NNZ 小块 + SIMD（原 student4）。历史测量数值保持不变。报告 Markdown / LaTeX / CSV 已同步更名，但 PDF 与生成图像需重新构建。

如果有其他你觉得有趣有价值的并行策略，也可以继续注册`spmv_omp_student_3`等函数，但`spmv_omp_student`的函数数量不得超过5个（上限为`spmv_omp_student_5`），超过5个的部分将不会被检查。**作业成绩与额外注册函数的数量无关**。

每次实现都会经过同一个 `check_result`，浮点误差允许绝对误差和相对误差各
`1e-10`。可以修改命令行参数来改变 skew 程度，例如：

```bash
./csr_spmv_lab --rows 20000 --cols 200000 \
  --normal-nnz 16 --long-rows 16 --long-nnz 80000 \
  --threads 16 --repeats 20
```

## 提交前核对

- 编译运行 `csr_spmv_lab.cpp`，确认 OpenMP 1 / OpenMP 2 都通过正确性检查。
- 使用 `python3 report/make_figures.py` 更新两张图，再使用 `bash report/build_pdf.sh` 重建 PDF；**仓库当前 PDF 与图仍为旧编号，不可直接提交**。
- 补做课程要求的 Linux `perf stat` 测量；由学生完成个人心路历程报告及必要的 AI 对话截图。
- 旧 `test_chunks.sh` 和 `compare_schedules.py` 已禁用：固定 `schedule(dynamic,128)` 不受 `OMP_SCHEDULE` 控制。
