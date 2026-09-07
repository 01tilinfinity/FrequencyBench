"""Plot top-five relation frequency composition before sampling.

Uses the existing median start-to-start frequency labels from
151,547 timelines (before the overlap fix). No dataset labels are changed.
Run: python codes/analysis/plot2.py
Outputs: data/analysis/plot/plot2/plot2_<PID>.png, plot2_<PID>.svg, plot2.csv.
"""

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, StrMethodFormatter
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
OUTPUT = ROOT / "data/analysis/plot/plot2"
PIDS = ["P54", "P39", "P17", "P2632", "P6"]
CLASSES = ["A-Day", "A-Few-Days", "A-Week", "A-Few-Weeks", "A-Month",
           "A-Few-Months", "A-Year", "A-Few-Years", "Many-Years"]


def main():
    manifest = json.loads((SOURCE.parent / "qlever_manifest.before_overlapfix.json").read_text())
    population = sum(r.get("n_valid", 0) for r in manifest.values())
    if population != 151_547:
        raise ValueError(f"Unexpected source population: {population}")
    matrix = []
    for pid in PIDS:
        counts, entities = Counter(), set()
        with (SOURCE / (pid + ".jsonl")).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["property"] != pid or row["subject"] in entities:
                    raise ValueError(f"Duplicate or mismatched entity-property record: {pid}")
                entities.add(row["subject"])
                counts[row["frequency_class"]] += 1
        expected = manifest[pid]
        if counts != Counter(expected["classes"]) or len(entities) != expected["n_valid"]:
            raise ValueError(f"Source counts disagree with manifest: {pid}")
        matrix.append([counts[c] for c in CLASSES])
    matrix = np.array(matrix, dtype=int)
    totals = matrix.sum(axis=1)
    share = 100 * matrix / totals[:, None]
    assert int(totals.sum()) == 114_326
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for i, pid in enumerate(PIDS):
        fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="white")
        fig.subplots_adjust(left=.11, right=.97, top=.86, bottom=.25)
        positions = np.arange(len(CLASSES))
        counts = matrix[i]
        ax.bar(positions, counts, width=.65, color="#3679ad")
        ax.set_xticks(positions, CLASSES, rotation=30, ha="right", fontsize=11)
        # Scale each relation separately so its internal distribution is readable.
        ax.set_ylim(0, float(counts.max()) * 1.16)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        ax.set_xlabel("Frequency", labelpad=12, fontsize=13)
        ax.set_ylabel("# of data", labelpad=10, fontsize=13)
        ax.set_title(f"{pid} - {manifest[pid]['label']} (n = {totals[i]:,})",
                     fontsize=16, pad=18)
        ax.grid(axis="y", alpha=.18)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", length=0)
        for j, count in enumerate(counts):
            ax.annotate(f"{count:,}", (j, count), xytext=(0, 5),
                        textcoords="offset points", ha="center", va="bottom", fontsize=11,
                        color="#263746" if count else "#8b959e")
        for suffix in ("png", "svg"):
            path = OUTPUT / f"plot2_{pid}.{suffix}"
            fig.savefig(path, dpi=180, facecolor="white")
            print(f"Saved {path}")
        plt.close(fig)
    with (OUTPUT / "plot2.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["property", "property_label", "frequency", "entity_count", "within_relation_pct"])
        for i, pid in enumerate(PIDS):
            for j, cls in enumerate(CLASSES):
                writer.writerow([pid, manifest[pid]["label"], cls, int(matrix[i, j]), float(share[i, j])])
    for i, pid in enumerate(PIDS):
        print(pid, json.dumps({c: {"n": int(matrix[i, j]), "pct": round(float(share[i, j]), 2)}
                              for j, c in enumerate(CLASSES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
