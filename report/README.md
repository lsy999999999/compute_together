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
