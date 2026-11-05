#!/usr/bin/env python3
"""End-to-end CLI checks using temporary synthetic data, not SIFT benchmarks."""

import argparse
import csv
import random
import struct
import subprocess
import tempfile
from pathlib import Path


def write_matrix(path, rows, kind, vecs=False):
    with path.open("wb") as stream:
        if not vecs:
            stream.write(struct.pack("<II", len(rows), len(rows[0])))
        for row in rows:
            if vecs:
                stream.write(struct.pack("<I", len(row)))
            stream.write(struct.pack("<" + kind * len(row), *row))


def fixtures(root):
    rng = random.Random(20261105)
    base = [[rng.randrange(256) for _ in range(17)] for _ in range(257)]
    base[7] = base[0][:]
    base[23] = base[0][:]
    queries = [base[0][:]] + [[rng.randrange(256) for _ in range(17)] for _ in range(12)]
    centers = [[rng.randrange(1024) / 4 for _ in range(17)] for _ in range(7)]
    # Two empty lists and one long list; matching IDs/index/ground truth.
    assignments = [[1 if i == 0 else 2 if i < 4 else 5 if i < 251 else 6]
                   for i in range(len(base))]
    truth = [sorted(range(len(base)),
                    key=lambda i: (sum((a - b) ** 2 for a, b in zip(q, base[i])), i))[:32]
             for q in queries]
    write_matrix(root / "sift_base.fbin", base, "f")
    write_matrix(root / "sift_query.fbin", queries, "f")
    write_matrix(root / "centroid_4096.fvecs", centers, "f", vecs=True)
    write_matrix(root / "cluster_id_4096.ivecs", assignments, "i", vecs=True)
    write_matrix(root / "gt.ibin", truth, "i")


def run(binary):
    with tempfile.TemporaryDirectory(prefix="ivf_synthetic_") as tmp:
        root = Path(tmp)
        fixtures(root)
        data_args = ["--base", str(root / "sift_base.fbin"),
                     "--queries-file", str(root / "sift_query.fbin"),
                     "--centroids", str(root / "centroid_4096.fvecs"),
                     "--cluster-ids", str(root / "cluster_id_4096.ivecs"),
                     "--gt", str(root / "gt.ibin"), "--queries", "13", "--k", "10"]
        calls = 0
        for strategy in ("serial", "exact", "std", "omp1", "omp2"):
            modes = ("off", "on") if strategy.startswith("omp") else ("off",)
            for simd in modes:
                for threads, batch, nprobe, grain in ((1, 1, 1, 1), (4, 5, 3, 8), (4, 1, 7, 64)):
                    command = [str(binary), *data_args, "--only", strategy, "--simd", simd,
                               "--threads", str(threads), "--batch", str(batch),
                               "--nprobe", str(nprobe), "--grain", str(grain), "--mode", "check"]
                    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
                    if result.returncode or "correctness=PASS" not in result.stdout:
                        raise RuntimeError(f"{' '.join(command)}\n{result.stdout}{result.stderr}")
                    calls += 1
        # The normal benchmark path must write a usable SIMD-tagged CSV.
        path = root / "smoke.csv"
        result = subprocess.run(
            [str(binary), *data_args, "--only", "omp2", "--simd", "on",
             "--threads", "4", "--batch", "5", "--nprobe", "3", "--grain", "8",
             "--warmup", "1", "--repeats", "2", "--csv", str(path)],
            text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 2
        for row in rows:
            assert row["strategy"] == "omp2" and row["simd"] == "on"
            assert row["correctness"] == "PASS" and float(row["time_ms"]) > 0
        for arguments in (("--simd", "bad"), ("--only", "std", "--simd", "on")):
            result = subprocess.run([str(binary), *arguments], text=True, capture_output=True, timeout=10)
            assert result.returncode != 0 and "simd" in result.stderr.lower()
        print(f"PASS: {calls} synthetic CLI checks, benchmark CSV, SIMD option validation")
        print("Synthetic correctness data only; SIFT1M performance remains to be measured on Linux.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("./ivf_lab"))
    run(parser.parse_args().binary.resolve())
