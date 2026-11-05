# 实验二报告与复核记录

- `experiment_report.pdf`：四页报告草稿，已逐页渲染检查；学生核实后可用于提交。
- `experiment_report.md`：可编辑正文，与 PDF 内容一致。
- `all_metrics.md`：40 个配置的完整时间范围、QPS、Recall 和延迟附录。
- `audit.json`：独立复核的统计和工具回退数据。
- `input_files.sha256`：本次下载的 491 个原始文件的完整性摘要。
- `figures/`：线程扩展图，以及粒度散点和 Recall/QPS 关系图；PNG / PDF 双格式。

原始结果：`../results/download_from_server/server_full_20261105_124550/`。原始文件保持不变。计时代码提交为 `32481fd77f2f4600f45fff87a66ea1a307c159db`。

## 复核与重建

在 `openmp_ivf_lab` 目录执行。复核只使用 Python 标准库，支持 Python 3.10+：

```bash
python3 scripts/audit_experiments.py \
  results/download_from_server/server_full_20261105_124550 --out report
```

数据目录存在时额外核对五个文件的 SHA-256；不存在时不会伪报本机数据已核对。计时源码哈希必须与服务器记录一致。当前审计针对本轮 P=32 的正式实验组数。

绘图需要 matplotlib / numpy；报告需要 reportlab / pypdf / Pillow：

```bash
python3 report/make_figures.py \
  results/download_from_server/server_full_20261105_124550
python3 report/build_report.py
```

本机生成 PDF 时嵌入 macOS 黑体。其他系统使用 ReportLab 的 STSong-Light CID 字体，需重新渲染确认字体显示正常。重建后应检查正文恰为四页。

## 交稿前剩余事项

1. 学生阅读并核实实现、数据、结论和 AI 使用声明。
2. P=32 是虚拟机可见预算，宿主物理核心分配未知；若教师要求真实物理核扩展性，需要向资源提供者确认。
3. grain=4096 的十次结果波动大，报告已保留并注明无法归因。若要对该配置形成结论，应交替复测 1024 与 4096；不影响已完成的 A–E 数据归档。
4. perf 缺少对应内核工具，按题目允许回退 GNU time；报告中明确为整个进程统计。
5. 学生本人撰写 300–1500 字心路历程，按题目要求附技术问答截图及求助/参考来源。该部分没有生成或润色。

代码、原始 CSV 和工具输出可随材料打包；SIFT 数据、可执行文件及本机构建目录无需提交。
