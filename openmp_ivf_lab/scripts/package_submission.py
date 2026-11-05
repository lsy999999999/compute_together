#!/usr/bin/env python3
"""Package reproducible lab materials, excluding SIFT data and executables."""
import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT=Path(__file__).resolve().parents[1]
PREFIX='刘师妤_2024201568_IVF'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=ROOT/'results/download_from_server/server_full_20261105_124550')
    parser.add_argument('--out',type=Path,default=ROOT/'submission/IVF_刘师妤_2024201568_待补个人材料.zip')
    args=parser.parse_args()
    assert json.loads((ROOT/'report/audit.json').read_text())['status']=='PASS'
    assert json.loads((args.results/'manifest.json').read_text())['status']=='PASS'
    assert (ROOT/'report/experiment_report.pdf').exists()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for directory in (ROOT,ROOT/'scripts',ROOT/'tests',ROOT/'report'):
        paths=directory.rglob('*') if directory.name=='report' else directory.iterdir()
        for path in paths:
            if not path.is_file() or '__pycache__' in path.parts:continue
            if path.suffix in ('.cpp','.h','.py','.sh','.md','.pdf','.png','.json','.sha256') or path.name in ('Makefile','.gitignore'):
                files.append((path,Path(PREFIX)/'openmp_ivf_lab'/path.relative_to(ROOT)))
    sources=[args.results]
    pilot=ROOT/'results/download_from_server/server_20261105_112425'
    if pilot.exists():sources.append(pilot)
    for source in sources:
        for path in source.rglob('*'):
            if path.is_file():
                files.append((path,Path(PREFIX)/'openmp_ivf_lab/results/download_from_server'/source.name/path.relative_to(source)))
    readme='''# 实验二材料（待学生核实并补充个人材料）

四页报告：openmp_ivf_lab/report/experiment_report.pdf
可编辑正文、完整表与复核记录位于同一 report 目录。
源码和测试：openmp_ivf_lab/，正式实验代码提交为 32481fd。
原始 CSV、构建、环境与工具输出：openmp_ivf_lab/results/download_from_server/。

Linux 复现：在 openmp_ivf_lab 执行 bash scripts/run_all.sh /var/dataset。
完整命令与指标定义见 EXPERIMENTS.md 和 SERVER_TEST.md。
数据未打包：sift_base.fbin、sift_query.fbin、gt.ibin、centroid_4096.fvecs、cluster_id_4096.ivecs。
这些配套文件的形状和 SHA-256 在原始结果 manifest.json / dataset.sha256 中。

正式结果为 VM 上 P=32 的客户机 CPU 预算，宿主物理核心分配未知。
perf 缺少内核工具，已保留错误，回退 GNU time 的整个进程统计。
grain=4096 波动较大，报告未据此作确定性原因判断。

交稿前：学生核实报告和 AI 使用声明；本人撰写 300–1500 字心路历程；
按作业要求附技术问答截图及求助、参考来源。此压缩包未包含上述个人材料。
'''
    with ZipFile(args.out,'w',compression=ZIP_DEFLATED,compresslevel=6) as archive:
        archive.writestr(PREFIX+'/交稿前说明.md',readme)
        for path,target in sorted(files):archive.write(path,str(target))
    with ZipFile(args.out) as archive:
        assert archive.testzip() is None
        names=archive.namelist()
        assert not any('/dataset/' in name or '/build/' in name or '__pycache__' in name for name in names)
        assert len(names)==len(set(names))
    print(f'{args.out}\n{len(names)} files; {args.out.stat().st_size:,} bytes; ZIP integrity PASS')


if __name__=='__main__':main()
