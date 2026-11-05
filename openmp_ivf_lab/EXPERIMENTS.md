# A–E 实验与性能工具

## 在服务器运行

从仓库更新后，在 `openmp_ivf_lab` 目录执行：

```bash
bash scripts/run_all.sh /var/dataset
```

脚本自动编译、运行公共/学生实现测试和 CLI 测试、保存向量化报告，再进行 A–E、std::thread 对照和性能工具采集。结果保存在新的 `results/server_full_时间戳/`，原结果保持不变。数据目录不同时替换 `/var/dataset`。

默认根据当前进程的 CPU 亲和性、可见 core/socket ID、可读 cgroup CPU 配额和 `OMP_THREAD_LIMIT` 选择预算 P；同一个可见核心最多选一个硬件线程。整数线程预算不超过 CPU 配额的向下取整值，配额小于一核时使用一线程并保留原配额。

可以限制本轮使用的核心预算，例如：

```bash
bash scripts/run_all.sh /var/dataset --cores 8
```

虚拟机中的 core/socket ID 是客户机拓扑，宿主机物理核心分配单独记为未知。`manifest.json` 保留可见 CPU、选中的 CPU、配额来源和虚拟化标记；报告应据此说明实验资源，不能把客户机的 32 个可见 CPU 直接写成 32 个已确认的宿主机物理核心。

Q 默认 128，若小于 4P 则自动增大到 4P。每个计时配置预热一次，正式重复十次，每次完整检查所有结果。两组固定 batch 为 1 和 4P，大 batch 不随当前线程数 p 改变。线程数取 1、2、4、……并补上 P。

## CPU 集合和绑定

Linux 下各版本由 `taskset` 启动，使用相同的 P 个 CPU 集合。OpenMP 使用显式的 `OMP_PLACES` 和 `OMP_PROC_BIND=close`；`std::thread` 在每次创建的工作线程中调用 `pthread_setaffinity_np`，第 t 个逻辑工作槽绑定到同一 CPU 列表的第 t 项。串行与调用线程绑定到列表第一项。std::thread 的创建、绑定和 join 都计入检索函数时间。

公共设置为 `OMP_DYNAMIC=FALSE`、`OMP_MAX_ACTIVE_LEVELS=1`、`OMP_WAIT_POLICY=PASSIVE`；可用 `--wait-policy active` 另开一轮实验。原始环境、实际子进程设置、构建日志、动态库、源码和二进制哈希都保存。OpenMP 统计还检查实际团队大小；绑定端点和实际承担候选计算的线程数由独立统计运行记录。

`--pin-cpus` 是底层主线程/std 绑定选项；OpenMP 的 places 与绑定设置由总脚本同时配置，不应单独用它代替 OpenMP 环境变量。

## 实验配置

所有配置使用同一套完整的 SIFT1M、中心和列表编号，k=10；默认 nprobe=8、grain=1024、公共标量候选距离。中心选择始终使用公共标量函数。

| 输出 | 改变的主要变量 | 固定与比较条件 |
| --- | --- | --- |
| A_scaling.csv | p=1,2,4,…,P | omp1/omp2；batch=1 和固定 4P；相对同 batch 串行 IVF 计算加速比与效率 |
| B_order.csv | 原始、C(q) 升序、C(q) 降序 | omp1/omp2，p=P、batch=4P、同一查询池、同一距离与 grain |
| C_grain.csv | 64、256、1024、4096 | omp2、p=P、batch=4P；记录任务数、临时数组及合并阶段诊断 |
| D_nprobe.csv | 1、8、32 | omp2、p=P、batch=4P；记录候选数、Recall 与 QPS |
| E_simd.csv | 距离开关 off/on | omp1/omp2，分别 p=1 与 p=P；同 batch=4P，保存编译器证据 |
| std_compare.csv | std / omp1 | p=P、batch=4P、公共标量距离、相同 CPU 集合与对应绑定位置 |

完全相同的配置只测一次，各组通过 `run_id` 引用这次测量；例如 C 的 grain=1024 可复用 A 中的相同配置。`all_runs.csv` 列出全部不同配置。A 的加速比分子始终是串行 IVF；E 的 `simd_speedup` 只比较同一策略、线程数与参数下的 off/on。

查询顺序由 `--query-order original|candidates-asc|candidates-desc` 控制。只排列前 Q 个查询，同时同步排列 ground truth，保留 `query_order.csv` 中的原始查询编号。候选数预计算只用于实验排序和统计核对；实际检索的每次调用仍在计时内部重新选择中心、扫描候选和维护 Top-k，不复用前一次答案。脚本检查同一 nprobe 下每个原始查询的候选数与各策略、各顺序的 Recall 保持一致。

## 延迟与重复计时

每个 `run_编号/` 包含：

- `repeats.csv`：十次正式重复的总检索时间、QPS、Recall 和正确性。
- `batch_samples.csv`：每次重复、每个同步 batch 调用的墙钟时间和实际查询数，包含不足 batch 的最后一批。
- `query_order.csv`：排列后的位置、原始查询编号和候选数。
- `diagnostics_*.csv`：另跑一次统计得到的查询、线程、batch 和列表记录。
- `bench.log`、`diagnostics.log`：实际命令与输出。

每轮总时间 T 为所有同步 batch 调用时间之和。CSV 写入、输出检查和预热不计入 T；函数内部的中心选择、分块、分配和重置临时数组、距离、Top-k、合并、线程管理与同步都在计时范围内。

`sample_p50_ms`、`sample_p95_ms` 对正式重复的所有 batch 样本使用 `(n−1)*p` 线性插值。batch=1 时是单查询延迟；batch>1 时是 batch 完成时间，不除以 batch 大小冒充查询响应时间。原始样本保留每一批的查询数，便于单独检查最后一批。

## 独立统计与阶段诊断

`--mode stats --stats-prefix 路径` 另运行一次检索，使用编译期统计模板实例；正常 bench 实例不执行工作量计数、CPU 采样或阶段时钟。诊断运行的时间不作为正式性能时间。

每个查询的候选数通过独立的标量中心选择再次核对；每批检查所有线程候选数之和等于查询候选数之和、子任务计数对齐、完成查询数对齐，并再次完整检查输出。线程记录中的 t 是团队/分块逻辑槽；std 每次调用创建新线程，因此它不是跨 batch 保持不变的 OS 线程 ID。

B 记录列表长度、C(q) 的中位数和最大值，以及逻辑工作槽 t 的 W_t 和 `max(W_t)/mean(W_t)`。线程 CSV 保留闲置线程的零计数。`actual_threads` 是建立的工作线程数，`active_candidate_threads` 是这批实际计算了候选距离的线程数，两者分开记录。`first_cpu/last_cpu` 是工作记录时的端点采样，不是完整的 CPU 迁移轨迹。

omp2 的查询阶段为：标量中心选择、分块及局部结果分配、任务生成/执行/等待、局部 Top-k 合并。阶段均用该查询的墙钟区间表示。多个查询并行时，区间可能重叠；字段中的 `*_query_wall_ms_sum` 是区间之和，不能解释为整批耗时或各线程 CPU 时间。

C 的阶段诊断用于支持 grain 与任务/合并成本的分析；正式性能以不带统计的 wall time 为准。每块最多 grain 个候选，B 块产生 B 个候选子任务和该查询的一个父任务。局部结果占至少 `B*k*sizeof(Neighbor)`，CSV 记录数组实际 capacity 对应的字节数。

`query_known_buffer_bytes_*` 只统计局部结果、块描述和异常记录数组；`query_child_heap_upper_bytes_max` 单独给出该查询活动子任务 Top-k 堆的保守上界。它们不包含 OpenMP 任务对象、分配器头、中心选择临时数组或父任务合并堆，不是整个进程或 batch 的峰值内存。

## perf 的范围和回退

脚本分别测量串行 IVF、omp2 和 std。每个版本使用同一大 batch、同一数据和标量距离，单独启动 `perf stat`：

```text
perf stat --delay=-1 --control=fifo:控制管道,确认管道 -x ';' -o counters.csv -e 事件 -- 程序参数
```

程序加载数据、计算参考并完成预热后，才首次发送 enable。每次正式重复在所有 batch 检索调用前 enable，循环结束后 disable，收到相应 ack 才继续；结果检查和 CSV 打印都在 disable 后。`control.csv` 必须恰好含十对确认过的 enable/disable。边界内还包括少量计时和控制代码开销，因此计数范围描述为“检索循环及其少量控制开销”。

perf 使用默认的事件继承，不设置 `--no-inherit`。事件在工作负载启动前以禁用状态创建；预热时建立的 OpenMP 工作线程，以及正式计时中建立和退出的 std 线程都属于工作负载的继承范围。保存实际命令和对应的独立线程统计作为范围说明；实际事件是否支持由服务器工具输出判断。

优先尝试 task-clock、cycles、instructions、cache-misses、context-switches、cpu-migrations；如果工具失败或有效事件不足两个，再尝试软件事件。原始计数、单位、运行时间和 running-percent 字段保留，未支持/未计数的项记为 unavailable。派生计数除以正式重复的总查询数或总候选数，排除预热；不对缺失硬件事件填值。

若 perf 权限、内核或工具版本不支持，保留每次尝试的错误，改为 `/usr/bin/time -v`。回退明确测整个进程，包含加载、参考、预热和检查，与检索函数墙钟 CSV 分开保存。脚本不修改权限，不使用 sudo。`perf_status.json` 和 `perf/status.csv` 区分 measured、whole_process_only、unavailable；不会把回退称为硬件计数结果。

## 本机验证与正式结果

开发时可以使用：

```bash
python3 scripts/run_experiments.py --data-dir dataset \
  --out results/local_pipeline_validation_new \
  --cores 2 --quick --allow-local --no-build --skip-perf
```

`--quick` 仅重复两次，并标记 quick_validation；macOS 本机不做 Linux CPU 绑定或真实 perf。正式服务器命令不要添加这些开发选项。最新验证范围见 STAGE2_VALIDATION.md。

成功结束显示 `COMPLETE:` 和结果目录。把整个 `server_full_时间戳/` 下载回来即可继续分析；若中途报错，也保留该目录的 manifest、命令日志和原始数据，以错误位置为依据处理。

参考：[perf stat](https://man7.org/linux/man-pages/man1/perf-stat.1.html)、[OpenMP 5.2 规范](https://www.openmp.org/spec-html/5.2/openmp.html)。
