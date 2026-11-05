#!/usr/bin/env python3
"""Plots from frozen raw repeats; error bars are min/max, not confidence limits."""
import argparse
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

COLORS = {'omp1':'#3775BA','omp2':'#0F4D92','serial':'#B64342'}


def read(path):
    with path.open(newline='') as stream: return list(csv.DictReader(stream))


def apply_publication_style():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':15,
                         'axes.linewidth':1.7,'axes.spines.top':False,'axes.spines.right':False,
                         'legend.frameon':False,'pdf.fonttype':42,'svg.fonttype':'none'})


def finalize_figure(fig, path):
    fig.tight_layout(pad=1.4)
    for ext in ('png','pdf'): fig.savefig(path.with_suffix('.'+ext),dpi=300,bbox_inches='tight')
    plt.close(fig)


def main(source, out):
    out.mkdir(parents=True,exist_ok=True)
    apply_publication_style()
    a=read(source/'A_scaling.csv')
    fig,axes=plt.subplots(1,2,figsize=(12,3.8))
    for ax,batch,title in zip(axes,(1,128),('(a) Single-query batches','(b) Batch = 128')):
        for strategy,marker in (('omp1','o'),('omp2','s')):
            group=[r for r in a if r['strategy']==strategy and int(r['batch'])==batch]
            x=np.array([int(r['threads']) for r in group])
            y=np.array([float(r['speedup']) for r in group])
            baseline=float(group[0]['speedup'])*float(group[0]['median_ms'])
            lo=baseline/np.array([float(r['max_ms']) for r in group])
            hi=baseline/np.array([float(r['min_ms']) for r in group])
            ax.errorbar(x,y,yerr=[y-lo,hi-y],color=COLORS[strategy],marker=marker,
                        linewidth=2,capsize=3,label=strategy)
        ax.axhline(1,color=COLORS['serial'],linestyle='--',linewidth=1.2,label='Serial IVF')
        ax.set_xscale('log',base=2); ax.set_xticks([1,2,4,8,16,32],[1,2,4,8,16,32])
        ax.set(xlabel='Threads',ylabel='Speedup over serial IVF',title=title)
        ax.set_ylim(bottom=0);ax.legend(fontsize=11)
    finalize_figure(fig,out/'scaling')
    fig,axes=plt.subplots(1,2,figsize=(12,3.8))
    grain=read(source/'C_grain.csv')
    x=np.arange(len(grain)); med=np.array([float(r['median_ms']) for r in grain])
    axes[0].bar(x,med,color=COLORS['omp2'],alpha=.8,edgecolor='black',linewidth=.8)
    for i,r in enumerate(grain):
        times=[float(z['time_ms']) for z in read(source/r['run_id']/'repeats.csv')]
        axes[0].scatter(i+np.linspace(-.12,.12,len(times)),times,color='#B64342',s=14,zorder=3)
    axes[0].set_xticks(x,[r['grain'] for r in grain]);axes[0].set(xlabel='Maximum candidates per block (grain)',
        ylabel='Retrieval time (ms)',title='(a) Task size: all 10 repeats')
    d=read(source/'D_nprobe.csv')
    axes[1].plot([float(r['recall'])*100 for r in d],[float(r['qps'])/1000 for r in d],
                 color=COLORS['omp2'],marker='o',linewidth=2)
    for r in d:
        axes[1].annotate('nprobe='+r['nprobe'],(float(r['recall'])*100,float(r['qps'])/1000),
                         xytext=(4,7),textcoords='offset points',fontsize=11)
    axes[1].set(xlabel='Recall@10 (%)',ylabel='Throughput (thousand queries/s)',
                 title='(b) Search range: fixed 32 threads',xlim=(20,103),ylim=(5,24))
    finalize_figure(fig,out/'sensitivity')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('--out',type=Path,default=Path('report/figures'))
    args=parser.parse_args();main(args.source,args.out)
