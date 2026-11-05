# OpenMP IVF-Flat 实验代码

这是 [向量检索作业](openmp_ivf_topk_lab.pdf) 的实验代码，使用 SIFT1M 数据和已经训练好的 IVF 索引。现已补全两种 OpenMP 策略、`std::thread` 对照和可切换的 SIMD 候选距离函数。算法、任务缓冲区和 Top-k 合并说明见 [IMPLEMENTATION.md](IMPLEMENTATION.md)。

## 编译和运行

进入解压后的代码目录，执行：

```bash
make
make test
make smoke
```

正式实验使用支持 C++17 和 OpenMP 的 g++，运行环境为 64 位 little-endian Linux。索引训练结果已经导出，编译时不需要链接 Faiss。默认编译选项是 `-O3 -std=c++17 -fopenmp -pthread`，完整选项见 `Makefile`。改过编译选项后，用 `make clean && make` 重新编译。

macOS 可用 Apple Clang 和 Homebrew `libomp` 做本地正确性验证；`Makefile` 自动设置编译和链接选项。缺少库时执行 `brew install libomp`。`make test` 同时运行原公共测试和新增学生实现测试；`make smoke` 用临时生成的小型合成数据测试真实 CLI 和 CSV，不需要下载 SIFT。合成数据检查不能代替 SIFT1M 的正式实验。

完整 SIFT1M 本机检查已执行，记录见 [VALIDATION.md](VALIDATION.md)。服务器操作见 [SERVER_TEST.md](SERVER_TEST.md)，可通过 `scripts/validate_real_data.py` 自动运行真实数据检查和一组初步计时。`dataset/` 已加入 Git 忽略规则，数据保留在本机或服务器。

正式 A–E、std 对照和性能工具采集已接入：在服务器执行 `bash scripts/run_all.sh /var/dataset`。脚本自动保存构建、测试、输入哈希、原始计时、独立工作量统计、向量化证据和 perf/回退输出，详见 [EXPERIMENTS.md](EXPERIMENTS.md)。

2026-11-05 的正式服务器结果已独立复核：40 配置、400 次重复与 16,910 个 batch 样本通过核对。四页报告草稿与完整指标见 [report/README.md](report/README.md)。原始结果保留于本机下载目录，未新增上传至 GitHub；可用 `scripts/package_submission.py` 将代码、报告、原始 CSV 和工具日志打包，个人材料由学生补充。

先运行串行版本：

```bash
./ivf_lab --only serial --queries 128 --batch 32 --csv serial.csv
```

这条命令处理前 128 个查询，每批 32 个，预热一次后重复 10 次。结果会与串行参考逐项比较，终端显示时间和 Recall，CSV 保存每次重复的数据。

只想检查结果时，可以使用 `--mode check`。下面两条命令分别检查扫描全部列表的 IVF 和全库检索：

```bash
./ivf_lab --only serial --queries 4 --batch 1 --nprobe 4096 --mode check
./ivf_lab --only exact --queries 4 --batch 1 --mode check
```

## 数据文件

程序默认从课程指定的 `/var/dataset/` 读取下面五个文件。源码仓库不包含这些数据；应先确认所登录的服务器有课程配套数据。数据位于其他目录时，通过 `--base`、`--queries-file`、`--gt`、`--centroids` 和 `--cluster-ids` 指定五个实际路径。

| 文件 | 内容 |
| --- | --- |
| `sift_base.fbin` | 1,000,000 个 128 维数据库向量 |
| `sift_query.fbin` | 10,000 个 128 维查询向量 |
| `gt.ibin` | 每个查询的 1000 个近邻编号，共 10,000 行 |
| `centroid_4096.fvecs` | Faiss 训练得到的 4096 个中心，每个中心 128 维 |
| `cluster_id_4096.ivecs` | 每个数据库向量所属的列表编号，共 1,000,000 行，每行一个编号 |

中心和列表编号是 Faiss 训练后的导出结果。`cluster_id_4096.ivecs` 的第 i 行对应数据库中的第 i 个向量，因此数据库、中心和列表编号这三份文件要配套使用。加载时，程序把同一列表的向量排到一起，并保留原始编号；这个过程约需 1 GiB 内存，不计入检索时间。

读取函数声明在 `ivf_io.h` 中：

```cpp
auto index = ivf::read_ivf("/var/dataset/sift_base.fbin",
                          "/var/dataset/centroid_4096.fvecs",
                          "/var/dataset/cluster_id_4096.ivecs");
auto queries = ivf::read_fbin("/var/dataset/sift_query.fbin");
auto gt = ivf::read_ibin("/var/dataset/gt.ibin");
```

`.fbin` 和 `.ibin` 的开头是两个 `uint32`，依次表示行数、维数，后面是连续的 `float32` 或 `int32` 数据。`.fvecs` 和 `.ivecs` 则在每一行前放一个 `int32` 维数，再存这一行的数据。四种格式都有对应的读取函数；主程序的查询文件固定使用 `.fbin`，ground truth 固定使用 `.ibin`。

`queries.row(i)` 返回第 i 个查询。列表 l 中的向量位于 `[index.list_ptr[l], index.list_ptr[l+1])`，用 `index.vector(p)` 访问向量，用 `index.ids[p]` 取得它的原始编号。`index.centroid(l)` 返回列表中心。

## 学生实现

`ivf_student.cpp` 实现了三个函数：

- `search_omp_student_1`：把不同查询分给不同线程。
- `search_omp_student_2`：把一个查询的候选分成多个任务，分别计算后合并 Top-k。
- `search_std_thread`：用 `std::thread` 实现按查询分块的版本，与 OpenMP 对比。

两个 OpenMP 实现用 `--simd off|on` 切换公共标量距离与自编的 `omp simd` 距离，默认 `off`。中心选择始终使用原来的标量函数；`std`、`serial` 和 `exact` 保持标量距离，传入 `--simd on` 会明确报错。

三个函数的参数相同，声明在 `ivf_search.h` 的 `ivf` 命名空间中：

```cpp
void search_omp_student_1(const IVFIndex& index, const float* queries,
                         std::size_t count, const SearchOptions& options,
                         Neighbor* output);
```

一次调用处理一个 batch。输入数据只读，`queries` 中有 `count * index.dim` 个元素，`output` 已分配 `count * options.k` 个位置。第 q 个查询的第 rank 个结果写到 `output[q * options.k + rank]`。`SearchOptions` 中的 `k`、`nprobe`、`threads`、`grain` 分别控制结果数、搜索列表数、线程数和候选块大小。

可以直接使用已有的 `select_lists`、`l2_distance_scalar`、`TopK` 和 `better`。调用 `TopK::finish` 后，结果已经排好序并写入输出，不要再往这个 TopK 对象里添加候选。

分别用 `--only omp1`、`--only omp2`、`--only std` 运行。新增测试覆盖单/多线程、不同 batch 和 grain、空列表、长列表、等距、候选不足 k、k=1 和全列表检索。还需在课程配套数据上通过完整检查，再进行性能实验。

```bash
./ivf_lab --only omp1 --threads 4 --queries 128 --batch 32 --simd off --mode check
./ivf_lab --only omp2 --threads 4 --queries 128 --batch 1 --grain 256 --simd on --mode check
./ivf_lab --only std --threads 4 --queries 128 --batch 32 --mode check
make vector-report
```

`make vector-report` 在 `build/vectorization.txt` 保存候选 SIMD 和公共标量代码的编译器向量化报告。报告应在正式实验服务器上重新生成，以实际编译结果描述 SIMD 开关两侧的代码。

## 参数和输出

运行 `./ivf_lab --help` 可查看参数。

| 参数 | 默认值或用途 |
| --- | --- |
| `--only` | 默认 `serial`，也可选 `std`、`exact`、`omp1`、`omp2` |
| `--mode` | 默认 `bench`；`check` 只运行并检查一次 |
| `--queries` / `--batch` | 前 128 个查询，每批最多 32 个 |
| `--k` / `--nprobe` | 10 / 8 |
| `--threads` / `--grain` | 4 / 1024 |
| `--simd` | 默认 `off`；两个 OpenMP 版本可用 `on` |
| `--query-order` | `original` / `candidates-asc` / `candidates-desc`；同步重排 ground truth |
| `--batches-csv` | 正式重复中每个同步 batch 调用的原始时间 |
| `--mode stats` / `--stats-prefix` | 单独运行统计，输出查询/线程/batch/列表四份 CSV |
| `--pin-cpus` | Linux 主线程/std 线程绑定列表；总脚本同时设置 OpenMP places 和绑定 |
| `--repeats` / `--warmup` | 10 / 1；warmup 可以为 0 |
| `--base` / `--centroids` / `--cluster-ids` | 指定数据库、中心、列表分配文件 |
| `--queries-file` / `--gt` | 指定查询 `.fbin` 和 ground truth `.ibin` |
| `--csv` | 保存每次正式重复的数据；文件已存在时会覆盖 |

计时从调用检索函数开始，到这一批的结果全部算完为止，包括中心选择、候选扫描、Top-k、线程管理和同步。数据加载、参考结果计算、检查和打印都在计时之外。程序汇总各批时间，再输出多次重复的最小值、中位数、最大值和 QPS。

每次运行都会重置并检查全部输出。结果按距离、编号升序排列，编号必须与参考一致，距离容差为 `atol=rtol=1e-10`。候选不足 k 个时，余下位置填 `id=-1, distance=+inf`。当 `nprobe=nlist` 时，参考结果改用全库扫描。

CSV 记录策略、请求线程数、查询数、batch、k、nprobe、grain、SIMD 开关、查询顺序、重复编号、时间、QPS、Recall 和检查结果。独立 stats 模式采集候选数、线程工作量、团队大小、活动候选线程数、任务/数组大小和阶段诊断；总脚本从逐 batch 原始样本计算延迟分位数。`std` 创建 `min(threads, 当前 batch 查询数)` 个线程；计时 CSV 的 `threads` 记录请求值，统计 CSV 单独记录实际值。数据路径、编译选项和运行环境请记在报告中。

`--only` 只选择要测的检索函数。总脚本使用 perf 的延迟启动与 FIFO 控制，在预热后开计数、结果检查前关计数并等待 ack。直接对整个程序执行普通 `perf stat` 仍包含加载和参考计算；范围与回退说明见 EXPERIMENTS.md。

## 文件说明

| 文件 | 内容 |
| --- | --- |
| `ivf_io.h/.cpp` | 数据和索引读取 |
| `ivf_search.h/.cpp` | 距离、Top-k、串行检索、结果检查和 Recall |
| `ivf_student.cpp` | 两种 OpenMP、SIMD 候选距离和 `std::thread` 实现 |
| `ivf_profile.h/.cpp` | 独立统计结构、Linux 绑定与 perf FIFO 确认协议 |
| `ivf_lab.cpp` | 参数解析、运行、计时和 CSV 输出 |
| `tests/ivf_tests.cpp` | 小型数据、文件读取和结果检查的测试 |
| `tests/ivf_student_tests.cpp` | 学生实现的边界情况、随机小型索引和多线程检查 |
| `tests/smoke_cli.py` | 临时合成文件的端到端 CLI、CSV 检查 |
| `tests/experiment_modes.py` | 排序、统计、延迟、配额和 perf 控制协议检查 |
| `scripts/validate_real_data.py` | 完整 SIFT1M 的 24 组检查与 12 组初步计时 |
| `scripts/run_all.sh` / `run_experiments.py` | 正式 A–E、std 与性能工具采集入口 |
| `IMPLEMENTATION.md` | 并行划分、缓冲区生命周期和合并说明 |
