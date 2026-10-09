# NNZ 调度对照实验

`student1` 为每个实际线程分配一个固定 NNZ 块；`student2` 默认分成约 `4 * omp_get_max_threads()` 个块，用 `schedule(dynamic, 1)` 领取。NNZ 很少时块数不超过 NNZ，全空矩阵保留一个块。实际线程数即使被运行时减少，所有块仍会被处理。

`student1` 和 `student2` 共用段内 SIMD 乘加及部分和合并代码。每个块把边界行的部分和写入自己的槽位，并行结束后按块编号合并；块完成顺序不同不会造成并发写入同一输出行。

动态块调度适用于各线程处理同等 NNZ 的耗时不一致时，例如每行固定开销、缓存命中和线程运行速度不同。当前实验支持“动态小块可改善耗时”的结论，不能单独证明差异来自 CPU 的异构核心。

## 复现

在项目根目录运行。本机为 Apple Clang 21.0.0、macOS 26.5.2 arm64，使用 Homebrew libomp，未设置线程绑定或 `OMP_*` / `KMP_*` 环境变量。

```bash
clang++ -O2 -std=c++17 -Xpreprocessor -fopenmp \
  -I/opt/homebrew/opt/libomp/include \
  -L/opt/homebrew/opt/libomp/lib \
  -Wl,-rpath,/opt/homebrew/opt/libomp/lib \
  -lomp -pthread experiments/nnz_schedule_benchmark.cpp \
  -o /private/tmp/nnz_schedules
python3 experiments/measure_nnz_schedules.py /private/tmp/nnz_schedules
```

Linux 上编译命令为：

```bash
g++ -O2 -std=c++17 -fopenmp -pthread \
  experiments/nnz_schedule_benchmark.cpp -o /private/tmp/nnz_schedules
```

每个配置 10 轮，每轮预热并检查结果后计时 100 次，策略顺序用固定随机种子 20261005 打乱。结果为每轮平均耗时的中位数，单位 ms。块分配、边界搜索、并行调度和合并全部计入耗时；检查与矩阵生成不计入。

`nnz_schedules_raw.csv` 和 `nnz_schedules_summary.csv` 分别保留当前代码的原始数据及中位数、最小值、最大值。`nnz_schedules_pilot_*` 为注册 `student2` 前的候选实现数据，不能直接与当前数据配对计算收益。

## 当前结果

除注明的选项外，使用主程序默认矩阵参数。

| 配置 | student4 | student1 | student2 |
| --- | ---: | ---: | ---: |
| 默认，1 线程 | 0.668635 | 0.501096 | 0.504035 |
| 默认，2 线程 | 0.346147 | 0.264049 | 0.264302 |
| 默认，4 线程 | 0.207385 | 0.157681 | 0.160866 |
| 默认，8 线程 | 0.182433 | 0.169632 | 0.141329 |
| 默认，8 线程，seed=7 | 0.198233 | 0.174641 | 0.154416 |
| 默认，8 线程，seed=42 | 0.178861 | 0.176135 | 0.150277 |
| 普通行 1 NNZ，1 条长行 100000 NNZ，8 线程 | 0.097545 | 0.041887 | 0.041009 |
| 无长行，8 线程 | 0.068298 | 0.066957 | 0.068584 |
| 普通行 0 NNZ，2 条长行各 20000 NNZ，8 线程 | 0.028597 | 0.026481 | 0.029880 |
| 20000 行、200000 列、普通行 16 NNZ、16 条长行各 80000 NNZ，8 线程 | 0.296714 | 0.267283 | 0.240387 |

默认 8 线程下，`student2` 相对 `student1` 耗时降低 16.7%，相对 `student4` 降低 22.5%。另外两个默认规模随机种子下，相对 `student1` 降低约 11.6% 和 14.7%；较大偏斜矩阵下降低约 10.1%。默认 1、2、4 线程的收益不足以证明值得增加调度开销；大量空行且 NNZ 很少时，`student2` 慢约 12.8%。因此保留两个 NNZ 策略。

## 调度消融

为了区分“块更小”和“采用动态调度”的影响，驱动保留相同的 NNZ 切块与 SIMD，比较不同块数和调度。默认 8 线程下：

| 调度 | 块数 | 中位耗时 ms |
| --- | ---: | ---: |
| student1，固定块 | 8 | 0.169632 |
| static 小块 | 32 | 0.168885 |
| dynamic 小块 | 16 | 0.153695 |
| student2，dynamic 小块 | 32 | 0.141329 |
| dynamic 小块 | 64 | 0.147112 |
| dynamic 小块 | 128 | 0.146650 |

只把固定块细分为 32 个 static 块，收益很小；相同的 32 个块用 dynamic 后明显改善，支持本例中动态领取任务起作用的解释。增加到 64 或 128 块没有持续改善，说明分块、领取任务、写入部分和及串行合并等开销需要权衡。每线程 4 块是本机实验选出的折中，不保证在其他机器或矩阵上最优。

## 正确性

`check_nnz_strategies.cpp` 验证所有四种 OpenMP student 策略。包含 9 种边界矩阵和 200 个随机矩阵，线程数为 1、2、3、4、8、16，每种配置换向量调用 3 次，共 15048 次检查（新版已扩大覆盖范围，但需在提交环境中重新运行确认）。包含全空矩阵、首尾及中间空行、线程数多于 NNZ、一行被多个块拆分。每次先将输出填为 NaN，再检查所有行有限且满足原来的 `1e-10` 判定。

本次分别使用正式 `-O2` OpenMP 构建、AddressSanitizer/UndefinedBehaviorSanitizer 构建、`OMP_DYNAMIC=true OMP_THREAD_LIMIT=2` 的运行及关闭 OpenMP 的串行回退验证。SIMD 和拆行改变浮点累加顺序，报告需要说明；误差阈值保持原样。

```bash
clang++ -O2 -std=c++17 -Xpreprocessor -fopenmp \
  -I/opt/homebrew/opt/libomp/include \
  -L/opt/homebrew/opt/libomp/lib \
  -Wl,-rpath,/opt/homebrew/opt/libomp/lib \
  -lomp -pthread experiments/check_nnz_strategies.cpp \
  -o /private/tmp/check_nnz
/private/tmp/check_nnz
```
