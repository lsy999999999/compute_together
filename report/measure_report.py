import csv
import io
import statistics
import subprocess
import sys
from pathlib import Path


def main():
    executable = Path(sys.argv[1]).resolve()
    directory = Path(__file__).resolve().parent
    cases = [(f"default_t{t}", ["--threads", str(t)]) for t in (1, 2, 4, 8, 10)] + [
        ("one_dominant", ["--threads", "8", "--normal-nnz", "1", "--long-rows", "1", "--long-nnz", "100000"]),
        ("no_long", ["--threads", "8", "--long-rows", "0"]),
        ("empty_short", ["--threads", "8", "--normal-nnz", "0", "--long-rows", "2"]),
        ("large_skew", ["--threads", "8", "--rows", "20000", "--cols", "200000", "--normal-nnz", "16", "--long-rows", "16", "--long-nnz", "80000"]),
        ("default_seed7", ["--threads", "8", "--seed", "7"]),
        ("default_seed42", ["--threads", "8", "--seed", "42"]),
    ]
    raw, summary = [], []
    for name, arguments in cases:
        result = subprocess.run([str(executable), "--repeats", "100", *arguments],
                                capture_output=True, text=True, check=True)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        for row in rows:
            raw.append({"case": name, "strategy": row["strategy"],
                        "trial": int(row["trial"]), "ms": float(row["ms"])})
        medians = {}
        for strategy in dict.fromkeys(row["strategy"] for row in rows):
            values = [float(row["ms"]) for row in rows if row["strategy"] == strategy]
            median = statistics.median(values)
            summary.append({"case": name, "strategy": strategy, "median_ms": median,
                            "min_ms": min(values), "max_ms": max(values)})
            medians[strategy] = median
        print(name + ": " + ", ".join(f"{s}={t:.6f}" for s, t in medians.items()), flush=True)
    for filename, rows in (("measurements_raw.csv", raw), ("measurements_summary.csv", summary)):
        with (directory / filename).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
