"""Top-five properties: stored timeline-entry counts by frequency class.

Run: python codes/analysis/plot5.py
Each observation is len(row['timeline']) for one entity-property pair, NOT
the number of value changes or n_statements (which can exclude deprecated rows).
Uses the unchanged before_overlapfix population used by the previous plots.
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.cbook import boxplot_stats
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
OUTPUT = ROOT / "data/analysis/plot/plot5"
PIDS = ["P54", "P39", "P17", "P2632", "P6"]
CLASSES = ["A-Day", "A-Few-Days", "A-Week", "A-Few-Weeks", "A-Month",
           "A-Few-Months", "A-Year", "A-Few-Years", "Many-Years"]


def draw_boxes(ax, stats, positions):
    ax.bxp(stats, positions=positions, widths=.55, patch_artist=True,
           showmeans=True, manage_ticks=False,
           boxprops={"facecolor": "#b7d2e6", "edgecolor": "#3679ad"},
           medianprops={"color": "#263746", "linewidth": 1.8},
           whiskerprops={"color": "#3679ad"}, capprops={"color": "#3679ad"},
           meanprops={"marker": "D", "markerfacecolor": "#de713b",
                      "markeredgecolor": "white", "markersize": 6},
           flierprops={"marker": "o", "markersize": 3, "markerfacecolor": "none",
                       "markeredgecolor": "#3679ad", "alpha": .5})
    ax.set_xlim(-.65, len(CLASSES) - .35)
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
    ax.tick_params(axis="x", length=0)


def main():
    manifest = json.loads((SOURCE.parent / "qlever_manifest.before_overlapfix.json").read_text())
    if sum(r.get("n_valid", 0) for r in manifest.values()) != 151_547:
        raise ValueError("Unexpected source population")
    top = sorted(manifest, key=lambda p: (-manifest[p].get("n_valid", 0), int(p[1:])))[:5]
    if top != PIDS:
        raise ValueError(f"Top-five properties changed: {top}")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table, observations, mismatches = [], [], {}
    for pid in PIDS:
        groups = defaultdict(list)
        seen = set()
        mismatch = 0
        with (SOURCE / f"{pid}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["property"] != pid or row["subject"] in seen:
                    raise ValueError(f"Duplicate or mismatched row: {pid}")
                seen.add(row["subject"])
                count = len(row["timeline"])
                if count < 3:
                    raise ValueError("Unexpected timeline length")
                mismatch += count != row["n_statements"]
                cls = row["frequency_class"]
                groups[cls].append(count)
                observations.append([pid, row["subject"], cls, count, row["n_statements"]])
        if Counter({c: len(a) for c, a in groups.items()}) != Counter(manifest[pid]["classes"]):
            raise ValueError(f"Manifest class counts disagree: {pid}")
        if len(seen) != manifest[pid]["n_valid"]:
            raise ValueError(f"Manifest population disagrees: {pid}")
        mismatches[pid] = mismatch
        stats, positions = [], []
        for j, cls in enumerate(CLASSES):
            values = groups[cls]
            if not values:
                table.append([pid, manifest[pid]["label"], cls, 0] + [""] * 8)
                continue
            s = boxplot_stats(values, whis=1.5, autorange=False)[0]
            # Coincident outliers have identical positions; draw each value once.
            s["fliers"] = np.unique(s["fliers"])
            stats.append(s)
            positions.append(j)
            table.append([pid, manifest[pid]["label"], cls, len(values),
                          min(values), s["q1"], s["med"], s["mean"], s["q3"],
                          max(values), s["whislo"], s["whishi"]])
        maximum = max(max(a) for a in groups.values() if a)
        zoom = maximum > 200
        if zoom:
            fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True,
                                     gridspec_kw={"height_ratios": [1, 2]}, facecolor="white")
            fig.subplots_adjust(left=.12, right=.97, top=.84, bottom=.20, hspace=.28)
            for ax in axes:
                draw_boxes(ax, stats, positions)
            axes[0].set_ylim(0, maximum * 1.08)
            axes[0].set_title("Full range (all observations)", loc="left", fontsize=10)
            axes[1].set_ylim(0, 22)
            axes[1].set_title("Zoom: 0–22 entries (same data)", loc="left", fontsize=10)
            axes[0].tick_params(axis="x", labelbottom=False)
            fig.supylabel("# of timeline entries per entity", x=.025, fontsize=13)
            main_ax = axes[1]
        else:
            fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="white")
            fig.subplots_adjust(left=.11, right=.97, top=.80, bottom=.27)
            draw_boxes(ax, stats, positions)
            ax.set_ylim(0, maximum * 1.12)
            ax.set_ylabel("# of timeline entries per entity", labelpad=10, fontsize=13)
            main_ax = ax
        main_ax.set_xticks(range(len(CLASSES)),
                          [f"{c}\n(n = {len(groups[c]):,})" for c in CLASSES],
                          rotation=30, ha="right", fontsize=10)
        main_ax.set_xlabel("Frequency", labelpad=12, fontsize=13)
        fig.suptitle(f"{pid} - {manifest[pid]['label']} (n = {len(seen):,})", fontsize=16, y=.97)
        legend = [Patch(facecolor="#b7d2e6", edgecolor="#3679ad", label="Box: middle 50%"),
                  Line2D([], [], color="#263746", linewidth=1.8, label="Median"),
                  Line2D([], [], color="none", marker="D", markerfacecolor="#de713b",
                         markeredgecolor="white", markersize=7, label="Mean")]
        fig.legend(handles=legend, loc="upper center", bbox_to_anchor=(.54, .925),
                   ncol=3, frameon=False, fontsize=10)
        for suffix in ("png", "svg"):
            path = OUTPUT / f"plot5_{pid}.{suffix}"
            fig.savefig(path, dpi=180, facecolor="white")
            print(f"Saved {path}")
        plt.close(fig)
    if len(observations) != 114_326:
        raise ValueError(f"Unexpected top-five population: {len(observations)}")
    for filename, header, rows in [
        ("plot5.csv", ["property", "property_label", "frequency", "entity_count", "min",
                       "q1", "median", "mean", "q3", "max", "whisker_low", "whisker_high"], table),
        ("plot5_observations.csv", ["property", "entity", "frequency", "timeline_entry_count",
                                    "evaluated_n_statements"], observations),
    ]:
        with (OUTPUT / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
    meta = {"source": str(SOURCE), "source_population": 151547, "top_five_population": len(observations),
            "properties": PIDS, "unit": "One entity-property pair per observation",
            "y": "len(timeline): all stored entries, including repeated values and any stored deprecated statements",
            "frequency": "Existing median start-to-start interval class, unchanged",
            "box": "25th to 75th percentile; center line = median; orange diamond = arithmetic mean",
            "whiskers": "Most extreme observed values within 1.5 IQR of the quartiles",
            "outliers": "Shown as circles; coincident values drawn once, no values removed from statistics",
            "small_groups": "n=0: no box; n=1: degenerate box; n labels show entity count",
            "axes": "Linear, independently scaled per property; P17 includes a full-range and a zoom panel",
            "stored_vs_evaluated_length_mismatch_counts": mismatches}
    (OUTPUT / "plot5.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
