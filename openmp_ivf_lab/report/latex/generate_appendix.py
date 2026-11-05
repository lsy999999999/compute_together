#!/usr/bin/env python3
"""Regenerate traceable LaTeX tables from the frozen downloaded CSVs."""
import csv
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[1]/'results/download_from_server/server_full_20261105_124550'


def rows(name):
    with (SOURCE/name).open() as f:return list(csv.DictReader(f))


def esc(value):
    return str(value).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')


def table(path,header,values,spec):
    content=[r'\begingroup\fontsize{9.3}{11.8}\selectfont',r'\setlength{\tabcolsep}{4pt}',
        r'\begin{longtable}{'+spec+'}',r'\toprule',header+r'\\\midrule\endfirsthead',
        r'\toprule',header+r'\\\midrule\endhead',r'\bottomrule\endfoot']
    content.extend(' & '.join(v)+r'\\' for v in values)
    content.extend([r'\end{longtable}',r'\endgroup'])
    path.write_text('\n'.join(content)+'\n')


def main():
    data=rows('all_runs.csv')
    order={'original':'原始','candidates-asc':'升序','candidates-desc':'降序'}
    table(HERE/'configurations.tex',r'编号 & 策略 & $p$ & batch & $n_{\rm probe}$ & grain & SIMD & 顺序',
          [[r['run_id'][-3:],r['strategy'],r['threads'],r['batch'],r['nprobe'],r['grain'],r['simd'],order[r['query_order']]] for r in data],
          'rlrrrrll')
    table(HERE/'measurements.tex',r'编号 & min (ms) & med (ms) & max (ms) & QPS & Recall (\%) & p50 (ms) & p95 (ms)',
          [[r['run_id'][-3:]]+[f'{float(r[k]):.4f}' for k in ('min_ms','median_ms','max_ms')]+
           [f"{float(r['qps']):.1f}",f"{float(r['recall'])*100:.4f}"]+
           [f'{float(r[k]):.4f}' for k in ('sample_p50_ms','sample_p95_ms')] for r in data],
          'rrrrrrrr')
    a=rows('A_scaling.csv')
    table(HERE/'scaling_metrics.tex',r'编号 & 策略 & $p$ & batch & $S$ & $E$ (\%)',
          [[r['run_id'][-3:],r['strategy'],r['threads'],r['batch'],f"{float(r['speedup']):.5f}",f"{float(r['efficiency'])*100:.3f}"] for r in a],
          'rlrrrr')
    manifest=json.loads((SOURCE/'manifest.json').read_text())
    evidence=[r'\begin{itemize}',r'\item 计时代码提交：\code{'+(SOURCE/'source_commit.log').read_text().splitlines()[-1]+'}。',
              r'\item 正式运行目录：\code{server_full_20261105_124550}，原始下载文件 491 个。',
              r'\item 逐文件摘要：\code{report/input_files.sha256}。',
              r'\item 五个数据文件及服务器记录的 SHA-256：\end{itemize}']
    for name,value in manifest['dataset'].items():
        digest=value['sha256']
        evidence.extend([r'\noindent\code{'+name+r'}\par',
            r'{\footnotesize\noindent\texttt{'+digest[:32]+r'\allowbreak '+digest[32:]+r'}\par}'])
    (HERE/'provenance.tex').write_text('\n'.join(evidence)+'\n')
    digest=hashlib.sha256((SOURCE/'all_runs.csv').read_bytes()).hexdigest()
    print(f'Generated frozen tables: 40 configurations, 24 scaling rows; all_runs.csv SHA256={digest}')


if __name__=='__main__':main()
