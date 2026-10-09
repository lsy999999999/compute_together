#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

threads="${1:-8}"
repeats="${2:-10000}"
trials="${3:-5}"
if ! command -v perf >/dev/null 2>&1; then
    echo "perf is required on Linux (install the perf package for your kernel)." >&2
    exit 1
fi

g++ -O2 -std=c++17 -fopenmp -pthread perf_spmv.cpp -o perf_spmv

mkdir -p report/perf
events="cycles,instructions,cache-references,cache-misses,context-switches,cpu-migrations"
echo "Checking availability of hardware counters..."
if ! perf stat -e cycles,instructions -- true >/dev/null 2>&1; then
    echo "Hardware perf events unavailable or permission denied. Check perf_event_paranoid and VM/PMU support." >&2
    exit 1
fi

for strategy in serial std_thread student1 student2 student3 student4; do
    echo "Measuring ${strategy} (threads=${threads}, repeats=${repeats}, trials=${trials})"
    perf stat -r "${trials}" -e "${events}" \
        -- ./perf_spmv "${strategy}" --threads "${threads}" --repeats "${repeats}" \
        > "report/perf/${strategy}_time.txt" \
        2> "report/perf/${strategy}_perf.txt"
done
echo "All six strategies measured. Results in report/perf/"
