# Linux 服务器测试步骤

## 正式 A–E、std 对照和性能工具（下一阶段）

初步服务器检查通过后，更新代码并执行：

```bash
cd ~/compute_together
git pull --ff-only origin main
cd openmp_ivf_lab
bash scripts/run_all.sh /var/dataset
```

脚本自动重新编译、测试和运行全部实验，预热一次、正式重复十次。输出放在新建的 `results/server_full_时间戳/`，不覆盖初步结果。它检测 CPU 亲和性和可读配额，固定大 batch=4P；虚拟机的客户机 CPU 预算单独标注。需要限制预算时，在末尾添加 `--cores 8`。

结束显示 `COMPLETE:` 后，下载整个新目录。目录包含 A–E 汇总、每次重复和每个 batch 的原始 CSV、独立统计、源码/环境记录、向量化证据与 perf 或回退输出。perf 权限或事件不支持时会保留错误，并尝试 `/usr/bin/time -v`，不需要 sudo。详细配置和计量说明见 [EXPERIMENTS.md](EXPERIMENTS.md)。

下方保留上一阶段的初步验证步骤，已有初步结果时可以直接使用本节命令。

## 1. 更新代码和编译

登录服务器后，已有 `~/compute_together` 仓库时执行：

```bash
cd ~/compute_together
git pull --ff-only origin main
cd openmp_ivf_lab
make clean
make -j4
make test
make smoke
```

首次使用这台服务器、尚未克隆仓库时，先执行下面两条命令，再从上面的 `cd openmp_ivf_lab` 继续：

```bash
cd ~
git clone https://github.com/lsy999999999/compute_together.git
```

`make test` 应输出公共测试 PASS 和学生实现的 2905 组策略配置 PASS；`make smoke` 应输出 21 组临时合成数据 CLI 检查 PASS。需要支持 C++17/OpenMP 的 g++ 和 Python 3.8 或更新版本。

## 2. 确认真实数据目录

课程服务器默认目录为 `/var/dataset`：

```bash
ls -lh /var/dataset/
```

需要五个配套文件：`sift_base.fbin`、`sift_query.fbin`、`gt.ibin`、`centroid_4096.fvecs` 和 `cluster_id_4096.ivecs`。实际目录不同，就把下面命令的 `--data-dir` 换成那个目录。脚本会检查每个文件的形状、字节数并保存 SHA-256，然后让 C++ 程序读取和检查全部输入。

如果服务器没有数据，可用本机终端的 `scp -P 端口 -r 本机dataset目录 用户@服务器:~/ivf_dataset` 上传已下载的五个文件，再指定 `--data-dir "$HOME/ivf_dataset"`。数据无需提交到 GitHub。

## 3. 一条命令验证真实数据

仍在服务器的 `openmp_ivf_lab` 目录执行：

```bash
python3 scripts/validate_real_data.py \
  --data-dir /var/dataset \
  --out "results/server_$(date +%Y%m%d_%H%M%S)" \
  --threads 4
```

程序执行 24 组真实数据检查，覆盖各策略的 SIMD 开关、单查询/批量查询和不同搜索范围，包括扫描全部列表时与独立全库扫描的比较。然后执行 12 组初步计时，每组预热一次、重复十次，并逐次完整检查输出。

只想先检查正确性时，在该命令后添加 `--checks-only`。输出目录必须是一个新目录，脚本不会覆盖已有结果。默认 `Q=128`、大 batch=32；这是一轮初步验证，正式 A 组实验需要根据实际可用物理核心数 P 把大 batch 固定为 4P，并保证 Q≥4P。

结尾应显示 `PASS: 24 real SIFT1M checks`。结果目录包含：

- `manifest.json`：环境、可用 CPU 集合、输入与二进制哈希、运行状态。
- `checks.csv` 和 `check_*.log`：正确性检查结果及命令。
- `bench_*.csv`、`bench_*.log` 和 `summary.csv`：正式重复的原始记录和汇总。
- `dataset.sha256`：五个输入文件的哈希。

把结尾输出和 `summary.csv` 发回，便可继续设计正式的线程数、查询顺序、grain、nprobe、SIMD 和 perf 实验。初步计时尚未增加作业要求的延迟分位数、线程工作量或 perf 范围控制。

## 4. 保存服务器的向量化证据

```bash
make vector-report
cat build/vectorization.txt
```

检查 `ivf_student.cpp` 的 SIMD 距离循环是否被向量化，并同时查看 `ivf_search.cpp` 公共标量源码的编译结果。服务器上重新生成的结果用于实验报告；本机 Apple Clang 的结果记录在 VALIDATION.md。
