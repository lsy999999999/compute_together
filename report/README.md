# 实验报告文件

- `experiment_report.md`：报告初稿，正文 4 页，另有 1 页附录。
- `experiment_report.pdf`：已经导出的 PDF。
- `measurements_raw.csv`、`measurements_summary.csv`：当前最终代码的统一实测数据。
- `benchmark_report.cpp`、`measure_report.py`：测量驱动和参数配置。
- `assets/`：图表、可单独使用的矢量图及学生已有的早期正确性截图。
- `supplement/`：早期 SIMD 消融的原始、汇总数据备份。

Linux `perf` 尚未测量，正文已明确说明，当前版本不能视为已满足该项作业要求。AI 使用声明已写入正文；心路历程报告没有代写或修改。

## 更新 PDF

本机已安装 Pandoc 和 Tectonic，并有可读取的 LaTeX 资源缓存。使用：

```bash
bash report/build_pdf.sh
```

脚本复制资源缓存至临时目录，离线构建，不修改用户原始缓存。当前排版使用 macOS 的 Songti SC、Times New Roman、Arial 和 Menlo；PDF 已嵌入字体，在其他机器阅读不需要这些字体。

图表由结构化 CSV 自动生成：

```bash
MPLCONFIGDIR=/private/tmp/spmv_report_mpl \
  /opt/homebrew/anaconda3/bin/python report/make_figures.py
```

重新测量正文数据的完整命令见报告附录；重测会更新本目录的测量 CSV。NNZ 调度消融复现命令见 `../experiments/README.md`。

## 提交前同步事项（2026-10-08）

2026-10-09：四种实现均重新注册为 student1/2/3/4：前两种为 NNZ 优化，后两种为行 static/dynamic 对照实现。四种都纳入 correctness、benchmark 和 perf。Markdown、LaTeX 和结构化 CSV 已同步更名，但**当前 experiment_report.pdf 以及 assets 中生成的图仍为旧编号**。必须先运行 `python3 report/make_figures.py`、再运行 `bash report/build_pdf.sh`，核对 PDF 图例与代码入口一致，才可提交。历史 student3 优化记录及 pilot CSV 保持当时命名。

## Linux perf 四种 OpenMP 对照

```bash
bash report/run_perf.sh 8 10000 5
```

按 `serial`、`std_thread`、`student1`、`student2`、`student3`、`student4` 分别运行，输出在 `report/perf/`。性能计数器测量整个独立程序；为减小矩阵生成和启动时间的占比，正式计数期间会重复调用同一个 SpMV 内核。不要把它误写为精确的 kernel-only 计数；如需严格的 kernel-only PMU 事件隔离，需要另外控制 `perf_event_open` 的 enable/disable 时段。Mac 和 Linux 的耗时不可直接配对计算加速比；`perf stat` 需在 Linux 执行，若硬件 PMU 不可用须记录为缺失。

## 最终运行正确性检查（必做）

四种策略注册完成后，仓库内未直接运行新版本的 macOS/OpenMP 二进制测试。应在目标机器运行：

```bash
g++ -O2 -std=c++17 -fopenmp -pthread experiments/check_nnz_strategies.cpp -o check_all_students
./check_all_students
```

成功时预期输出 `15048 correctness checks passed.`。这是预期结果而非已获验证的测试记录。`report/experiment_report.pdf` 必须在报告源文件更新后重新生成。
