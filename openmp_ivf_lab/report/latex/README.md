# LaTeX 报告

- `main.tex` / `main.pdf`：更充实的报告正文，编译结果为 4 页。
- `appendix.tex` / `appendix.pdf`：5 页独立附录，含实现依据、40 个配置的完整数据、完整扩展指标、异常重复及复现说明。
- `preamble.tex`：共同版式与字体配置。
- `../figures/*.pdf`：引用的矢量图。

正文补充了方案选择依据、任务数据所有权、局部 Top-k 证明、实际块数公式与中心/候选工作量的关系。原 Markdown/ReportLab 版本保留。

## 编译

从本目录使用 **XeLaTeX** 编译 `main.tex` 和 `appendix.tex`，或从 lab 根目录执行：

```bash
bash report/latex/build.sh
```

脚本优先使用 XeLaTeX，否则使用 Tectonic；本机已有 Tectonic 缓存时复制至临时可写目录并离线构建。Overleaf 选择 XeLaTeX，将此目录作为主文件目录，并保持上一级 `figures/` 路径，或将图片放在此目录并调整 graphicspath。

macOS 使用 Songti SC；缺少时回退 Fandol（TeX Live）。图表用冻结的服务器数据；原始数据存在时，可执行 `python3 report/latex/generate_appendix.py` 重新生成表格。编译时使用已包含的 `.tex` 表格即可，无需数据库或原始 CSV。

正文与附录分开提交，正文页数由编译后实际 PDF 核对。材料包未包含学生本人心路历程及问答截图。

本机已逐页检查排版；源码 ZIP 解压至独立临时目录后，正文与附录均重新编译通过，无缺字或 overfull 警告。
