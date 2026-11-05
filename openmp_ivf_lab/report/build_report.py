#!/usr/bin/env python3
"""Render the four-page Chinese report and a full metrics Markdown appendix."""
import csv
import html
import re
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'results/download_from_server/server_full_20261105_124550'


def rich(text):
    text=html.escape(text)
    text=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'<link href="\2" color="#0F4D92">\1</link>',text)
    text=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',text)
    text=re.sub(r'`([^`]+)`',r'<font color="#174E75">\1</font>',text)
    return text


def main():
    font_path=Path('/System/Library/Fonts/STHeiti Light.ttc')
    if font_path.exists():
        pdfmetrics.registerFont(TTFont('CJK',str(font_path)))
        pdfmetrics.registerFont(TTFont('CJK-Bold','/System/Library/Fonts/STHeiti Medium.ttc'))
    else:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        pdfmetrics.registerFontFamily('STSong-Light',normal='STSong-Light',bold='STSong-Light')
    font='CJK' if font_path.exists() else 'STSong-Light'
    if font=='CJK': pdfmetrics.registerFontFamily(font,normal=font,bold='CJK-Bold')
    base=dict(fontName=font,fontSize=9.4,leading=13.5,wordWrap='CJK',spaceAfter=5)
    body=ParagraphStyle('body',**base)
    title=ParagraphStyle('title',parent=body,fontSize=18,leading=23,spaceAfter=10)
    heading=ParagraphStyle('heading',parent=body,fontSize=12.2,leading=17,spaceBefore=5,spaceAfter=7)
    cell=ParagraphStyle('cell',parent=body,fontSize=8,leading=11,spaceAfter=0)
    caption=ParagraphStyle('caption',parent=body,fontSize=8,leading=10.5,alignment=TA_CENTER,spaceAfter=5)
    story=[]
    lines=(ROOT/'experiment_report.md').read_text().splitlines()
    width=A4[0]-32*mm
    i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1;continue
        if line=='<!-- pagebreak -->': story.append(PageBreak());i+=1;continue
        if line.startswith('# '): story.append(Paragraph(rich(line[2:]),title));i+=1;continue
        if line.startswith('## '): story.append(Paragraph(rich(line[3:]),heading));i+=1;continue
        if line.startswith('|'):
            data=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                fields=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+',x) for x in fields):
                    data.append([Paragraph(rich(x),cell) for x in fields])
                i+=1
            n=len(data[0]);weights=None
            if n==2: weights=[.23,.77]
            if n==3: weights=[.30,.43,.27]
            if n==7: weights=[.06,.14,.14,.16,.17,.16,.17]
            if n==5:
                if 'grain' in data[0][0].getPlainText(): weights=[.09,.12,.34,.25,.20]
                elif '策略' in data[0][0].getPlainText(): weights=[.10,.31,.12,.31,.16]
                else: weights=[.12,.23,.24,.20,.21]
            if n==4: weights=[.31,.23,.23,.23]
            table=Table(data,colWidths=[width*x for x in weights] if weights else [width/n]*n,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E8EFF6')),
                ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#51708E')),
                ('LINEBELOW',(0,-1),(-1,-1),.4,colors.HexColor('#9DA7B0')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),4),
                ('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),3),
                ('BOTTOMPADDING',(0,0),(-1,-1),3)]))
            story.extend([table,Spacer(1,6)]);continue
        image=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line)
        if image:
            from PIL import Image as PILImage
            path=ROOT/image.group(2)
            with PILImage.open(path) as img: iw,ih=img.size
            story.extend([Image(str(path),width=width,height=width*ih/iw),Paragraph(rich(image.group(1)),caption)])
            i+=1;continue
        story.append(Paragraph(rich(line),body));i+=1

    def footer(canvas,doc):
        canvas.setFont(font,8)
        canvas.setFillColor(colors.HexColor('#66717D'))
        canvas.drawString(16*mm,11*mm,'OpenMP IVF-Flat · SIFT1M · 2026-11-05')
        canvas.drawRightString(A4[0]-16*mm,11*mm,str(doc.page))
    document=SimpleDocTemplate(str(ROOT/'experiment_report.pdf'),pagesize=A4,
        leftMargin=16*mm,rightMargin=16*mm,topMargin=14*mm,bottomMargin=17*mm,
        title='OpenMP IVF-Flat 向量检索实验报告',author='刘师妤',allowSplitting=1)
    document.build(story,onFirstPage=footer,onLaterPages=footer)
    from pypdf import PdfReader
    pages=len(PdfReader(ROOT/'experiment_report.pdf').pages)
    print('PDF pages:',pages)
    assert pages==4,'Report must have exactly four pages; inspect and adjust layout'

    with (SOURCE/'all_runs.csv').open() as stream: rows=list(csv.DictReader(stream))
    fields=['run_id','strategy','threads','batch','nprobe','grain','simd','query_order',
            'min_ms','median_ms','max_ms','qps','recall','sample_p50_ms','sample_p95_ms']
    content=['# 完整配置指标附录','',
             '来源：server_full_20261105_124550。40 个不同配置，各预热 1 次并重复 10 次。',
             '时间单位 ms；Q=128，k=10。batch=1 的 p50/p95 为查询延迟，否则为批完成时间。',
             '本附录单独保存，不计入四页报告正文；原始重复与逐 batch 数据保留在下载目录。','',
             '| '+' | '.join(fields)+' |','| '+' | '.join(['---']*len(fields))+' |']
    for r in rows:
        vals=[f'{float(r[k]):.6f}' if k in fields[8:] else r[k] for k in fields]
        content.append('| '+' | '.join(vals)+' |')
    (ROOT/'all_metrics.md').write_text('\n'.join(content)+'\n')


if __name__=='__main__':main()
