"""Count distinct properties with at least one timeline in each frequency class.

Source: the original 151,547 pre-sampling timelines, before the overlap fix.
A property can count once in multiple classes; class counts are not disjoint.
Run: python codes/analysis/plot3.py
Outputs: data/analysis/plot/plot3/plot3.png, plot3.svg, plot3.csv.
Use --highlight-detention for a separate plot3_highlight_detention PNG/SVG.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, StrMethodFormatter

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
OUTPUT = ROOT / "data/analysis/plot/plot3"
CLASSES = ["A-Day", "A-Few-Days", "A-Week", "A-Few-Weeks", "A-Month",
           "A-Few-Months", "A-Year", "A-Few-Years", "Many-Years"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--highlight-detention", action="store_true",
                        help="Save a separate version highlighting the first four classes.")
    args = parser.parse_args()
    manifest = json.loads((SOURCE.parent / "qlever_manifest.before_overlapfix.json").read_text())
    properties = {cls: set() for cls in CLASSES}
    total = 0
    for path in sorted(SOURCE.glob("P*.jsonl"), key=lambda p: int(p.stem[1:])):
        class_counts = Counter()
        seen = set()
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["property"] != path.stem or row["subject"] in seen:
                    raise ValueError(f"Duplicate or mismatched entity-property record: {path}")
                seen.add(row["subject"])
                cls = row["frequency_class"]
                properties[cls].add(row["property"])
                class_counts[cls] += 1
                total += 1
        if class_counts != Counter(manifest[path.stem]["classes"]):
            raise ValueError(f"Counts disagree with manifest: {path.stem}")
    all_properties = set().union(*properties.values())
    if total != 151_547 or len(all_properties) != 379:
        raise ValueError(f"Unexpected population: {total} timelines, {len(all_properties)} properties")
    values = [len(properties[cls]) for cls in CLASSES]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="white")
    fig.subplots_adjust(left=.11, right=.97, top=.86, bottom=.25)
    positions = list(range(len(CLASSES)))
    colors = ["#d94b4b" if args.highlight_detention and j < 4 else "#3679ad"
              for j in positions]
    ax.bar(positions, values, width=.65, color=colors)
    ax.set_xticks(positions, CLASSES, rotation=30, ha="right", fontsize=11)
    ax.set_ylim(0, max(values) * 1.16)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.set_xlabel("Frequency", labelpad=12, fontsize=13)
    ax.set_ylabel("# of relations (properties)", labelpad=10, fontsize=13)
    ax.set_title("plot3 | Number of properties by frequency", fontsize=17, pad=18)
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0)
    for j, count in enumerate(values):
        ax.annotate(f"{count:,}", (j, count), xytext=(0, 5), textcoords="offset points",
                    ha="center", va="bottom", fontsize=12, color="#263746")
    if args.highlight_detention:
        # The annotation describes record composition, not the plotted property counts.
        bracket_y = max(values[:4]) + 40
        ax.plot([-.325, -.325, 3.325, 3.325],
                [bracket_y - 8, bracket_y, bracket_y, bracket_y - 8],
                color="#d94b4b", linewidth=1.5)
        ax.text(1.5, bracket_y + 7, "Most records: place of detention",
                ha="center", va="bottom", fontsize=11, color="#a52f2f")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stem = "plot3_highlight_detention" if args.highlight_detention else "plot3"
    for suffix in ("png", "svg"):
        path = OUTPUT / (stem + "." + suffix)
        fig.savefig(path, dpi=180, facecolor="white")
        print(f"Saved {path}")
    plt.close(fig)
    if args.highlight_detention:
        return
    with (OUTPUT / "plot3.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["frequency", "property_count", "property_ids"])
        for cls in CLASSES:
            ids = sorted(properties[cls], key=lambda p: int(p[1:]))
            writer.writerow([cls, len(ids), "|".join(ids)])
    print(json.dumps({"source_timelines": total, "unique_properties": len(all_properties),
                      "counts_by_frequency": dict(zip(CLASSES, values))}, indent=2))


if __name__ == "__main__":
    main()
