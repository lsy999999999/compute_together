import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
plt.rcParams.update({"font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.dpi": 300,
                     "font.family": "DejaVu Sans"})


def load(path):
    with path.open(newline="") as handle:
        return {(r["case"], r["strategy"]): r for r in csv.DictReader(handle)}


def main():
    data = load(ROOT / "measurements_summary.csv")
    threads = np.array([1, 2, 4, 8, 10])
    baseline = float(data[("default_t1", "serial")]["median_ms"])
    styles = [("std_thread", "std::thread", "#64748b", "o"),
              ("student1", "student1", "#2563eb", "s"),
              ("student2", "student2", "#d97706", "^"),
              ("student3", "student3", "#15803d", "D"),
              ("student4", "student4", "#be123c", "o")]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.45), layout="constrained")
    for strategy, label, color, marker in styles:
        times = np.array([float(data[(f"default_t{t}", strategy)]["median_ms"])
                          for t in threads])
        axes[0].plot(threads, baseline / times, color=color, marker=marker,
                     markersize=4, linewidth=1.3, label=label)
        axes[1].plot(threads, 100 * baseline / times / threads, color=color,
                     marker=marker, markersize=4, linewidth=1.3)
    axes[0].set_ylabel("Speedup vs. serial")
    axes[1].set_ylabel("Efficiency (%)")
    axes[0].set_ylim(0, 5.5)
    axes[1].set_ylim(0, 145)
    axes[1].axhline(100, color="#9ca3af", linestyle="--", linewidth=0.8)
    axes[0].legend(fontsize=7.5, ncol=2, loc="upper left", frameon=False)
    for axis in axes:
        axis.set_xlabel("Requested threads")
        axis.set_xticks(threads)
        axis.grid(axis="y", alpha=0.2)
    fig.savefig(ROOT / "assets/scaling.png")
    fig.savefig(ROOT / "assets/scaling.pdf")
    plt.close(fig)

    controls = load(ROOT.parent / "experiments/nnz_schedules_summary.csv")
    names = ["student3", "static_blocks4", "dynamic_blocks2", "student4",
             "dynamic_blocks8", "dynamic_blocks16"]
    labels = ["Fixed\n8 blocks", "Static\n32 blocks", "Dynamic\n16 blocks",
              "Dynamic\n32 blocks", "Dynamic\n64 blocks", "Dynamic\n128 blocks"]
    medians = np.array([float(controls[("default_t8", s)]["median_ms"]) for s in names])
    low = np.array([float(controls[("default_t8", s)]["min_ms"]) for s in names])
    high = np.array([float(controls[("default_t8", s)]["max_ms"]) for s in names])
    fig, axis = plt.subplots(figsize=(7.1, 2.1), layout="constrained")
    colors = ["#15803d", "#64748b", "#9f1239", "#be123c", "#9f1239", "#9f1239"]
    axis.bar(labels, medians, color=colors, width=0.6,
             yerr=np.vstack([medians - low, high - medians]),
             capsize=3, error_kw={"elinewidth": 0.8, "ecolor": "#374151"})
    axis.set_ylabel("Latency (ms)")
    axis.set_ylim(0, 0.23)
    axis.grid(axis="y", alpha=0.2)
    axis.set_axisbelow(True)
    for i, median in enumerate(medians):
        axis.text(i, 0.012, f"{median:.3f}", ha="center", va="bottom",
                  color="white", fontsize=9)
    fig.savefig(ROOT / "assets/ablation.png")
    fig.savefig(ROOT / "assets/ablation.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
