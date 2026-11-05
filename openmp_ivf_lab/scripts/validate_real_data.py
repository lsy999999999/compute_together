#!/usr/bin/env python3
"""Check SIFT1M strategies and optionally collect a bounded baseline comparison.

No external Python packages. Run from any directory; compile ivf_lab first.
This does not replace the assignment's full A-E/perf experiments.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = {
    "--base": ("sift_base.fbin", 1_000_000, 128, False),
    "--queries-file": ("sift_query.fbin", 10_000, 128, False),
    "--gt": ("gt.ibin", 10_000, 1000, False),
    "--centroids": ("centroid_4096.fvecs", 4096, 128, True),
    "--cluster-ids": ("cluster_id_4096.ivecs", 1_000_000, 1, True),
}
STRATEGIES = [("serial", "off"), ("std", "off"),
              ("omp1", "off"), ("omp1", "on"), ("omp2", "off"), ("omp2", "on")]


def inspect_data(directory):
    metadata = {}
    arguments = []
    for option, (name, rows, dim, vecs) in DATA_FILES.items():
        path = directory / name
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")
        expected_bytes = rows * (4 + dim * 4) if vecs else 8 + rows * dim * 4
        with path.open("rb") as stream:
            header = stream.read(4 if vecs else 8)
            actual_shape = struct.unpack("<I" if vecs else "<II", header)
            if actual_shape != ((dim,) if vecs else (rows, dim)) or path.stat().st_size != expected_bytes:
                raise RuntimeError(f"Unexpected SIFT1M shape/size: {path}")
            stream.seek(0)
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        metadata[name] = {"path": str(path), "rows": rows, "dim": dim,
                          "bytes": expected_bytes, "sha256": digest.hexdigest()}
        arguments.extend((option, str(path)))
    return metadata, arguments


def environment():
    result = {"platform": platform.platform(), "machine": platform.machine(),
              "python": platform.python_version(), "logical_cpus": os.cpu_count(),
              "omp_environment": {k: os.environ.get(k) for k in
                                  ("OMP_NUM_THREADS", "OMP_DYNAMIC", "OMP_PROC_BIND", "OMP_PLACES")}}
    if hasattr(os, "sched_getaffinity"):
        result["allowed_cpus"] = sorted(os.sched_getaffinity(0))
    for label, command in (("compiler", ["c++", "--version"]),
                           ("cpu", ["sysctl", "-n", "machdep.cpu.brand_string"]
                            if platform.system() == "Darwin" else ["lscpu"])):
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
            result[label] = proc.stdout + proc.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            result[label] = str(error)
    return result


def invoke(command, path):
    print(f"Running {path.stem}", flush=True)
    proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
    path.write_text(json.dumps(command) + "\n" + proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode or "correctness=PASS" not in proc.stdout:
        raise RuntimeError(f"Failed: {path}\n{proc.stdout}{proc.stderr}")
    return proc.stdout


def run(args):
    binary = args.binary.resolve()
    directory = args.data_dir.resolve()
    output = args.out.resolve()
    # Avoid mixing old results or silently overwriting a previous run.
    output.mkdir(parents=True, exist_ok=False)
    if not binary.is_file():
        raise RuntimeError(f"Compile first: make (binary missing: {binary})")
    metadata, data_args = inspect_data(directory)
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(),
                "environment": environment(), "dataset": metadata,
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "requested_threads": args.threads, "queries": args.queries,
                "batch": args.batch, "checks_only": args.checks_only,
                "status": "running", "note": "Bounded validation; full A-E/perf experiments remain."}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "dataset.sha256").write_text(
        "".join(f"{entry['sha256']}  {name}\n" for name, entry in metadata.items()), encoding="utf-8")
    checks = []
    # q, batch, nprobe, grain, k, threads; all-list runs use independent exact reference.
    settings = [(4, 1, 1, 64, 1, 1),
                (args.queries, 1, 8, 256, 10, args.threads),
                (args.queries, args.batch, 32, 1024, 10, args.threads),
                (2, 1, 4096, 4096, 10, args.threads)]
    for strategy, simd in STRATEGIES:
        for q, batch, nprobe, grain, k, threads in settings:
            tag = f"check_{strategy}_{simd}_q{q}_b{batch}_np{nprobe}_k{k}"
            command = [str(binary), *data_args, "--only", strategy, "--simd", simd,
                       "--queries", str(q), "--batch", str(batch), "--nprobe", str(nprobe),
                       "--grain", str(grain), "--k", str(k), "--threads", str(threads), "--mode", "check"]
            stdout = invoke(command, output / f"{tag}.log")
            recall = float(stdout.rsplit("=", 1)[1].strip())
            # serial normalizes the requested count to one inside ivf_lab.
            effective_threads = int(stdout.split("threads=", 1)[1].split()[0])
            checks.append(dict(strategy=strategy, simd=simd, queries=q, batch=batch,
                               nprobe=nprobe, k=k, requested_threads=threads,
                               threads=effective_threads, grain=grain,
                               correctness="PASS", recall=recall))
    with (output / "checks.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(checks[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(checks)

    if not args.checks_only:
        summaries = []
        for strategy, simd in STRATEGIES:
            for batch in sorted({1, args.batch}):
                threads = 1 if strategy == "serial" else args.threads
                tag = f"bench_{strategy}_{simd}_p{threads}_b{batch}"
                path = output / f"{tag}.csv"
                command = [str(binary), *data_args, "--only", strategy, "--simd", simd,
                           "--queries", str(args.queries), "--batch", str(batch), "--nprobe", "8",
                           "--grain", "1024", "--k", "10", "--threads", str(threads),
                           "--warmup", "1", "--repeats", "10", "--csv", str(path)]
                invoke(command, output / f"{tag}.log")
                with path.open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                if len(rows) != 10 or any(row["correctness"] != "PASS" for row in rows):
                    raise RuntimeError(f"Unexpected benchmark CSV: {path}")
                times = [float(row["time_ms"]) for row in rows]
                median = statistics.median(times)
                summaries.append(dict(strategy=strategy, simd=simd, threads=threads,
                                      queries=args.queries, batch=batch, nprobe=8, k=10, grain=1024,
                                      min_ms=min(times), median_ms=median, max_ms=max(times),
                                      qps=args.queries * 1000 / median,
                                      recall=float(rows[0]["recall"]), correctness="PASS"))
        with (output / "summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(summaries)
    manifest.update(status="PASS", checks=len(checks), finished_utc=datetime.now(timezone.utc).isoformat())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(checks)} real SIFT1M checks; results: {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "ivf_lab")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New output directory; must not exist")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--queries", type=int, default=128)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--checks-only", action="store_true")
    args = parser.parse_args()
    if args.threads < 1 or not 1 <= args.queries <= 10000 or args.batch < 1:
        parser.error("threads/batch must be positive; queries must be between 1 and 10000")
    run(args)
