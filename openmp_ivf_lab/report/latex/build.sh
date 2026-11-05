#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v xelatex >/dev/null 2>&1; then
  for ivf_tex in main appendix; do
    xelatex -interaction=nonstopmode -halt-on-error "$ivf_tex.tex"
    xelatex -interaction=nonstopmode -halt-on-error "$ivf_tex.tex"
  done
elif command -v tectonic >/dev/null 2>&1; then
  if [ -d "$HOME/Library/Caches/Tectonic/bundles/data" ]; then
    IVF_TEX_CACHE=$(mktemp -d "${TMPDIR:-/tmp}/ivf-latex.XXXXXX")
    trap 'rm -rf "$IVF_TEX_CACHE"' EXIT
    cp -R "$HOME/Library/Caches/Tectonic/." "$IVF_TEX_CACHE/"
    IVF_TEX_BUNDLE=""
    for ivf_candidate in "$IVF_TEX_CACHE"/bundles/data/*; do
      if [ -f "$ivf_candidate/article.cls" ]; then
        IVF_TEX_BUNDLE="$ivf_candidate"
        if [ ! -f "$ivf_candidate/SHA256SUM" ]; then
          printf '%s\n' "${ivf_candidate##*/}" > "$ivf_candidate/SHA256SUM"
        fi
        break
      fi
    done
    if [ -z "$IVF_TEX_BUNDLE" ]; then
      printf '%s\n' 'Cached LaTeX bundle not found.' >&2
      exit 1
    fi
    for ivf_tex in main appendix; do
      TECTONIC_CACHE_DIR="$IVF_TEX_CACHE" tectonic --bundle "$IVF_TEX_BUNDLE" \
        --only-cached --keep-logs "$ivf_tex.tex"
    done
  else
    tectonic --keep-logs main.tex
    tectonic --keep-logs appendix.tex
  fi
else
  printf '%s\n' 'Use XeLaTeX (e.g. Overleaf) or install Tectonic.' >&2
  exit 1
fi
