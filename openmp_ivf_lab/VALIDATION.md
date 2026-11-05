# 本机验证记录（2026-11-05）

本轮验证使用 macOS arm64，先完成小型合成数据检查，再使用用户下载到 `dataset/` 的完整 SIFT1M 和 IVF 数据检查。Linux 上的同机对照和作业要求的完整性能实验待运行。

## Apple Clang 21 + libomp

执行命令：

```bash
make -j3 all ivf_tests ivf_student_tests
make test
make smoke
make vector-report
```

发布编译使用 `-O3 -std=c++17 -Wall -Wextra -Wpedantic -pthread -Xpreprocessor -fopenmp`，链接 Homebrew libomp。

结果：

```text
PASS: matrix/index readers, malformed files, Top-k, correctness, recall
PASS: 2905 student strategy configurations; SIMD distances, threads 1/2/4/8, batches, ties, empty/long lists, padding, full scan
PASS: 21 synthetic CLI checks, benchmark CSV, SIMD option validation
```

学生实现检查覆盖 5 个策略/距离组合（std、omp1 标量/SIMD、omp2 标量/SIMD），包含输出前后哨兵、未写入槽位检查、单查询、非整批尾部、grain 小于 k、空列表、长列表、等距、候选不足 k，以及 1/3/17/128/129 维的固定种子随机索引。全列表检索使用独立的全库扫描参考。CLI 检查在临时目录写入配套的五种文件，运行正常读取、检索、结果检查和 CSV 路径，结束后删除合成数据。

## GCC 16.2.0 + libgomp

使用 Homebrew GCC 验证 GNU OpenMP 的编译兼容性，仍运行于 macOS arm64：

```bash
/opt/homebrew/opt/gcc/bin/g++-16 -I. -O3 -std=c++17 \
  -Wall -Wextra -Wpedantic -fopenmp -pthread \
  tests/ivf_student_tests.cpp ivf_io.cpp ivf_search.cpp ivf_student.cpp \
  -o build/ivf_student_tests_gcc
./build/ivf_student_tests_gcc
```

结果：同样通过 2905 组学生实现策略配置。正式服务器应使用其实际 GCC 和 OpenMP 运行时重跑。

## AddressSanitizer 与 UndefinedBehaviorSanitizer

使用 Apple Clang，以 `-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer` 编译学生实现测试，链接同一 libomp，再执行 `build/ivf_student_tests_sanitized`。2905 组策略配置全部通过，没有报告地址越界、悬空访问或未定义行为。该构建的编译器对 SIMD 循环报告未向量化；向量化证据采用独立的 O3 发布构建。

## 实际向量化报告

本机执行 `make vector-report` 后，报告包含：

```text
ivf_student.cpp:13:5: remark: vectorized loop (vectorization width: 4, interleaved count: 4)
   13 |     #pragma omp simd reduction(+:sum)

ivf_search.cpp:35:5: remark: vectorized loop (vectorization width: 4, interleaved count: 4)
   35 |     for (std::size_t j = 0; j < dim; ++j) {
```

这次编译中，自编 SIMD 循环和公共标量源码循环都被向量化。因此 `--simd off/on` 比较的是公共距离实现和显式 OpenMP SIMD 实现，不能把本机的 off 解释为无 SIMD 指令。正式报告应重新采集 Linux 服务器的编译器证据及运行时间。

## 完整 SIFT1M 数据验证

数据文件头与大小检查通过：数据库为 1,000,000 × 128，查询为 10,000 × 128，中心为 4096 × 128，列表编号为 1,000,000 × 1，ground truth 为 10,000 × 1000。五个文件的 SHA-256 保存在 [dataset.sha256](results/local_macos_sift1m_20261105/dataset.sha256)，便于在服务器核对是否使用同一套输入。

执行命令：

```bash
python3 scripts/validate_real_data.py --data-dir dataset \
  --out results/local_macos_sift1m_20261105 --threads 4
```

六个策略/距离组合（serial、std、omp1 标量/SIMD、omp2 标量/SIMD）分别检查四个配置，24 组全部通过。配置覆盖 `k=1`、`nprobe=1/8/32/4096`、`batch=1/32`、单线程和请求四线程。扫描全部列表时处理两个查询，并与独立全库扫描比较。

还运行了 12 组初步计时：上述六个组合分别使用 `batch=1/32`，Q=128、k=10、nprobe=8、grain=1024；serial 实际使用一线程，其余请求四线程。每组预热一次、正式重复十次，每次重复完整检查，全部通过；这些配置的 Recall@10 均为 0.7265625。

- [checks.csv](results/local_macos_sift1m_20261105/checks.csv)：真实数据检查配置和结果；`requested_threads` 为 CLI 请求值，`threads` 为程序采用值。
- [summary.csv](results/local_macos_sift1m_20261105/summary.csv)：12 组计时的最小值、中位数、最大值和 QPS。
- [manifest.json](results/local_macos_sift1m_20261105/manifest.json)：环境、输入哈希、二进制哈希和运行状态。
- 同目录 `bench_*.csv` 为每次重复的原始数据，`.log` 为实际命令和终端输出。

本机这轮没有设置 CPU 绑定；manifest 中保留了读取 CPU 型号被当前环境拒绝的原始错误。正式性能结论使用 Linux 服务器上的同机实验。

## 待在课程服务器执行

按 [SERVER_TEST.md](SERVER_TEST.md) 更新、编译，指定服务器上的配套数据目录，再运行相同验证脚本。随后收集五组性能实验、线程对照和 perf 数据，再据实撰写实验报告。
