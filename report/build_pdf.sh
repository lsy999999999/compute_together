#!/usr/bin/env bash
set -euo pipefail

SPMV_REPORT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SPMV_REPORT_DIR"
pandoc experiment_report.md --standalone --to=latex \
    --include-in-header=header.tex --resource-path=. \
    --output=experiment_report.tex

# A local cached bundle avoids network initialization during an offline build.
SPMV_TEX_CACHE="${SPMV_TEX_CACHE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/spmv-report-tex.XXXXXX")}"
if [[ ! -d "$SPMV_TEX_CACHE/bundles/data" ]]; then
    cp -R "$HOME/Library/Caches/Tectonic/." "$SPMV_TEX_CACHE"
fi
SPMV_TEX_BUNDLE=""
for candidate in "$SPMV_TEX_CACHE"/bundles/data/*; do
    if [[ -d "$candidate" && -f "$candidate/article.cls" ]]; then
        SPMV_TEX_BUNDLE="$candidate"
        if [[ ! -f "$candidate/SHA256SUM" ]]; then
            printf '%s\n' "${candidate##*/}" > "$candidate/SHA256SUM"
        fi
        break
    fi
done
if [[ -z "$SPMV_TEX_BUNDLE" ]]; then
    printf '%s\n' 'No cached Tectonic LaTeX bundle found.' >&2
    exit 1
fi
TECTONIC_CACHE_DIR="$SPMV_TEX_CACHE" tectonic \
    --bundle "$SPMV_TEX_BUNDLE" --only-cached --keep-logs \
    --outdir . experiment_report.tex
