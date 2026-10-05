import subprocess
import os
import re
import csv
import statistics
import random

# =========================
# Experiment configuration
# =========================
THREADS = 8
REPEATS = 100
TRIALS = 7

CHUNKS = [
    1, 2, 4, 8, 16, 32, 64,
    128, 192, 256, 320, 384,
    512, 768, 1024
]

EXECUTABLE = "./csr_spmv_lab"

RAW_FILE = "schedule_compare_raw.csv"
SUMMARY_FILE = "schedule_compare_summary.csv"


def extract_time(output, patterns):
    """
    Find timing line and return ms value.
    Supports both old labels:
        OpenMP 1 (TODO)
        OpenMP 2 (TODO)
    and renamed labels:
        OpenMP static
        OpenMP dynamic
    """
    for line in output.splitlines():
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
            match = re.search(r"([0-9.]+)\s*ms", line)
            if match:
                return float(match.group(1))

    raise RuntimeError(
        f"Could not find timing for patterns {patterns}\n\n{output}"
    )


def run_once(chunk):
    env = os.environ.copy()

    # Only OMP2 uses schedule(runtime)
    env["OMP_SCHEDULE"] = f"dynamic,{chunk}"

    result = subprocess.run(
        [
            EXECUTABLE,
            "--threads", str(THREADS),
            "--repeats", str(REPEATS)
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True
    )

    output = result.stdout

    if "All correctness checks passed." not in output:
        raise RuntimeError(
            f"Correctness check failed for chunk={chunk}\n{output}"
        )

    serial = extract_time(
        output,
        [r"^\s*serial\b"]
    )

    std_thread = extract_time(
        output,
        [r"std::thread"]
    )

    static = extract_time(
        output,
        [
            r"OpenMP\s+static",
            r"OpenMP\s+1"
        ]
    )

    dynamic = extract_time(
        output,
        [
            r"OpenMP\s+dynamic",
            r"OpenMP\s+2"
        ]
    )

    return {
        "serial": serial,
        "std_thread": std_thread,
        "static": static,
        "dynamic": dynamic
    }


raw_rows = []

print("=" * 72)
print("Paired OpenMP scheduling experiment")
print(f"threads = {THREADS}")
print(f"repeats = {REPEATS}")
print(f"trials  = {TRIALS}")
print("=" * 72)

# Run every chunk several times.
# Shuffle chunk order within each trial to reduce temperature/time-order bias.
for trial in range(1, TRIALS + 1):

    order = CHUNKS.copy()
    random.Random(2026 + trial).shuffle(order)

    print(f"\n===== Trial {trial}/{TRIALS} =====")

    for chunk in order:

        data = run_once(chunk)

        ratio = data["static"] / data["dynamic"]
        improvement = (
            (data["static"] - data["dynamic"])
            / data["static"]
            * 100.0
        )

        raw_rows.append({
            "trial": trial,
            "chunk": chunk,
            "serial_ms": data["serial"],
            "std_thread_ms": data["std_thread"],
            "static_ms": data["static"],
            "dynamic_ms": data["dynamic"],
            "static_over_dynamic": ratio,
            "dynamic_improvement_percent": improvement,
        })

        print(
            f"chunk={chunk:4d} | "
            f"static={data['static']:.3f} ms | "
            f"dynamic={data['dynamic']:.3f} ms | "
            f"static/dynamic={ratio:.3f}x"
        )


# =========================
# Save raw measurements
# =========================

with open(RAW_FILE, "w", newline="") as f:
    fieldnames = [
        "trial",
        "chunk",
        "serial_ms",
        "std_thread_ms",
        "static_ms",
        "dynamic_ms",
        "static_over_dynamic",
        "dynamic_improvement_percent",
    ]

    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(raw_rows)


# =========================
# Summarize by chunk
# =========================

summary_rows = []

for chunk in sorted(CHUNKS):

    rows = [r for r in raw_rows if r["chunk"] == chunk]

    serial = [r["serial_ms"] for r in rows]
    std_thread = [r["std_thread_ms"] for r in rows]
    static = [r["static_ms"] for r in rows]
    dynamic = [r["dynamic_ms"] for r in rows]

    ratios = [
        r["static_over_dynamic"]
        for r in rows
    ]

    improvements = [
        r["dynamic_improvement_percent"]
        for r in rows
    ]

    summary_rows.append({
        "chunk": chunk,

        "serial_median_ms":
            statistics.median(serial),

        "std_thread_median_ms":
            statistics.median(std_thread),

        "static_median_ms":
            statistics.median(static),

        "dynamic_median_ms":
            statistics.median(dynamic),

        "dynamic_std_ms":
            statistics.stdev(dynamic)
            if len(dynamic) > 1 else 0.0,

        "static_over_dynamic_median":
            statistics.median(ratios),

        "dynamic_improvement_percent_median":
            statistics.median(improvements),
    })


with open(SUMMARY_FILE, "w", newline="") as f:
    fieldnames = list(summary_rows[0].keys())

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(summary_rows)


# =========================
# Print final table
# =========================

print("\n")
print("=" * 94)
print(
    f"{'Chunk':>7} "
    f"{'Static':>10} "
    f"{'Dynamic':>10} "
    f"{'S/D':>9} "
    f"{'Dyn gain':>11} "
    f"{'Dyn std':>10}"
)
print("=" * 94)

for row in summary_rows:

    print(
        f"{row['chunk']:>7} "
        f"{row['static_median_ms']:>10.4f} "
        f"{row['dynamic_median_ms']:>10.4f} "
        f"{row['static_over_dynamic_median']:>9.3f} "
        f"{row['dynamic_improvement_percent_median']:>10.2f}% "
        f"{row['dynamic_std_ms']:>10.4f}"
    )

print("=" * 94)

best = min(
    summary_rows,
    key=lambda r: r["dynamic_median_ms"]
)

print()
print("Best dynamic configuration:")
print(f"  chunk          = {best['chunk']}")
print(
    f"  dynamic median = "
    f"{best['dynamic_median_ms']:.4f} ms"
)
print(
    f"  static median  = "
    f"{best['static_median_ms']:.4f} ms"
)
print(
    f"  static/dynamic = "
    f"{best['static_over_dynamic_median']:.3f}x"
)
print(
    f"  dynamic gain   = "
    f"{best['dynamic_improvement_percent_median']:.2f}%"
)

print()
print(f"Raw data:    {RAW_FILE}")
print(f"Summary:     {SUMMARY_FILE}")
