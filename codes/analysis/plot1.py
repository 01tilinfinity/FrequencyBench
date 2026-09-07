"""Plot unique entity counts for every property in the 151,547-timeline dataset.

Run from any directory: python codes/analysis/plot1.py
Outputs: data/analysis/plot/plot1/plot1.png and plot1.svg. Counts use the original
pre-sampling timelines, not the 820 labeled samples or the updated overlap filter.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
OUTPUT = ROOT / "data/analysis/plot/plot1"


def main():
    manifest_path = SOURCE.parent / "qlever_manifest.before_overlapfix.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = []
    total_rows = 0
    for path in sorted(SOURCE.glob("P*.jsonl"), key=lambda p: int(p.stem[1:])):
        entities = set()
        row_count = 0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if record["property"] != path.stem:
                    raise ValueError(f"Property mismatch in {path}")
                entities.add(record["subject"])
                row_count += 1
        if row_count != len(entities):
            raise ValueError(f"Duplicate entity-property timelines in {path}")
        if len(entities) != manifest[path.stem]["n_valid"]:
            raise ValueError(f"Count disagrees with manifest for {path.stem}")
        if entities:
            counts.append((path.stem, manifest[path.stem]["label"], len(entities)))
        total_rows += row_count
    if total_rows != 151_547 or len(counts) != 379:
        raise ValueError(f"Unexpected population: {total_rows} rows, {len(counts)} properties")
    counts.sort(key=lambda row: (-row[2], int(row[0][1:])))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    # A wide vector export lets every one of the 379 property labels be inspected.
    fig, ax = plt.subplots(figsize=(42, 9), facecolor="white")
    fig.subplots_adjust(left=.035, right=.995, bottom=.22, top=.82)
    positions = list(range(len(counts)))
    values = [row[2] for row in counts]
    ax.bar(positions, values, width=.82, color="#3679ad", linewidth=0)
    ax.set_xticks(positions, [f"{pid} - {label}" for pid, label, _ in counts],
                  rotation=90, fontsize=6.5)
    for tick_label, (_, _, count) in zip(ax.get_xticklabels(), counts):
        if count == 1:
            tick_label.set_bbox({"facecolor": "#fbd0df", "edgecolor": "none",
                                 "boxstyle": "square,pad=0.12"})
    ax.tick_params(axis="x", length=2, pad=3)
    ax.set_xlim(-1, len(counts))
    ax.set_ylim(0, max(values) * 1.16)
    ax.set_xlabel("Property (PID - label), sorted by entity count descending", labelpad=16, fontsize=16)
    ax.set_ylabel("Number of unique entities", fontsize=16)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.annotate(f"{values[0]:,}", (0, values[0]), xytext=(0, 8),
                textcoords="offset points", ha="center", fontsize=12)
    # Preserve the bar area height and allocate room for the longest property name.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_height = max(t.get_window_extent(renderer).height for t in ax.get_xticklabels()) / fig.dpi
    bottom_inches = max(1.98, label_height + 1.1)
    figure_height = bottom_inches + 5.4 + 1.62
    fig.set_size_inches(42, figure_height)
    fig.subplots_adjust(bottom=bottom_inches / figure_height, top=1 - 1.62 / figure_height)
    fig.suptitle("plot1 | Unique entities per property", fontsize=26, y=1 - .36 / figure_height)
    fig.text(.5, 1 - 1.035 / figure_height,
             f"All {len(counts)} properties with valid timelines | "
             f"{total_rows:,} entity-property pairs | Before random sampling | Linear y-axis",
             ha="center", fontsize=16, color="#465565")
    leaders = "\n".join(f"{pid} - {label}: {count:,}" for pid, label, count in counts[:5])
    ax.text(.06, .93, "Largest properties\n" + leaders, transform=ax.transAxes,
            ha="left", va="top", fontsize=15, linespacing=1.6,
            bbox={"facecolor": "#f3f6f9", "edgecolor": "none", "pad": 14})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg"):
        destination = OUTPUT / ("plot1." + suffix)
        fig.savefig(destination, dpi=180, facecolor="white")
        print(f"Saved {destination}")
    plt.close(fig)
    print(f"Verified {total_rows:,} entity-property pairs across {len(counts)} properties.")
    for pid, label, count in counts[:5]:
        print(f"{pid} | {label} | {count:,}")


if __name__ == "__main__":
    main()
