#!/bin/bash

THREADS=8
REPEATS=100
TRIALS=5

CHUNKS=(1 2 4 8 16 32 64 128 192 256 320 384 512 768 1024)

RAW_FILE="chunk_results.csv"
SUMMARY_FILE="chunk_summary.csv"

echo "chunk,trial,time_ms" > "$RAW_FILE"

echo "========================================"
echo "OpenMP dynamic chunk-size experiment"
echo "threads  = $THREADS"
echo "repeats  = $REPEATS"
echo "trials   = $TRIALS"
echo "========================================"

for chunk in "${CHUNKS[@]}"
do
    echo ""
    echo "Testing chunk = $chunk"

    export OMP_SCHEDULE="dynamic,$chunk"

    for ((trial=1; trial<=TRIALS; trial++))
    do
        output=$(./csr_spmv_lab \
            --threads $THREADS \
            --repeats $REPEATS)

        time_ms=$(echo "$output" | awk '/OpenMP 2/ {print $(NF-1)}')

        echo "  trial $trial: $time_ms ms"

        echo "$chunk,$trial,$time_ms" >> "$RAW_FILE"
    done
done

python3 << 'PY'
import csv
import statistics
from collections import defaultdict

data = defaultdict(list)

with open("chunk_results.csv", newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        chunk = int(row["chunk"])
        time = float(row["time_ms"])
        data[chunk].append(time)

with open("chunk_summary.csv", "w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "chunk",
        "mean_ms",
        "median_ms",
        "min_ms",
        "max_ms",
        "std_ms"
    ])

    print()
    print("==========================================================")
    print(f"{'Chunk':>8} {'Mean':>10} {'Median':>10} {'Min':>10} {'Std':>10}")
    print("==========================================================")

    for chunk in sorted(data):
        values = data[chunk]

        mean = statistics.mean(values)
        median = statistics.median(values)
        minimum = min(values)
        maximum = max(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0

        writer.writerow([
            chunk,
            mean,
            median,
            minimum,
            maximum,
            std
        ])

        print(
            f"{chunk:>8} "
            f"{mean:>10.4f} "
            f"{median:>10.4f} "
            f"{minimum:>10.4f} "
            f"{std:>10.4f}"
        )

print("==========================================================")
print()
print("Raw results saved to: chunk_results.csv")
print("Summary saved to:     chunk_summary.csv")
PY
