"""Annotate Plot 1's top, middle, and last five properties.

Run: python codes/analysis/plot1_5.py
Uses exactly the same verified population and ranking as plot1.py.
"""

import csv
import json

from plot1 import ROOT, SOURCE, OUTPUT, load_counts
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter


def select_groups(counts):
    middle = len(counts) // 2
    return [
        ("Top 5", "#d62728", list(range(5))),
        ("Middle 5", "#e47700", list(range(middle - 2, middle + 3))),
        ("Last 5 (Long tail)", "#218739", list(range(len(counts) - 5, len(counts)))),
    ]


def write_examples(counts, groups):
    # Missing labels were checked on the Wikidata pages linked in the report.
    # Values and frequency classes are verified against local source timelines.
    with (ROOT / "data/final/frequency_bench.csv").open(encoding="utf-8", newline="") as f:
        top = next(row for row in csv.DictReader(f) if row["property_id"] == "P54")
    examples = [
        {"entity_id": top["entity_id"], "entity": top["entity"],
         "property_id": top["property_id"], "value_id": top["value_id"],
         "value": top["value"], "frequency": top["frequency"]},
        {"entity_id": "Q3356809", "entity": "Norwegian National Road 9",
         "property_id": "P1824", "value_id": "", "value": "400",
         "frequency": "Many-Years"},
        {"entity_id": "Q178516", "entity": "Gucci", "property_id": "P12617",
         "value_id": "Q318149", "value": "Tom Ford", "frequency": "A-Few-Years"},
    ]
    lines = [
        "# Plot 1.5 groups and actual examples", "",
        "Population: 151,547 entity-property timelines across 379 properties, identical to Plot 1.",
        "Sort: unique entity count descending, then numeric PID ascending.",
        "Middle 5: ranks 188–192 (centered on rank 190). Last 5: ranks 375–379.",
        "The last five all have count 1; ties follow the existing PID order.",
        "Frequency is the source timeline's temporal frequency class, not property popularity.", "",
    ]
    for (name, color, indices), example in zip(groups, examples):
        members = {counts[i][0]: counts[i] for i in indices}
        pid = example["property_id"]
        assert pid in members
        source = SOURCE / f"{pid}.jsonl"
        with source.open(encoding="utf-8") as f:
            record = next(r for r in map(json.loads, f) if r["subject"] == example["entity_id"])
        raw_value = example["value_id"] or example["value"]
        assert record["frequency_class"] == example["frequency"]
        interval = next(item for item in record["timeline"] if item["value"] == raw_value)
        example.update(category=name, color=color, property=members[pid][1],
                       frequency_days=record["median_interval_days"],
                       start_time=interval["start"], end_time=interval.get("end"),
                       source=str(source.relative_to(ROOT)))
        lines.extend([f"## {name} ({color})", "", "| Rank | Property | Entity count |",
                      "|---|---|---:|"])
        for i in indices:
            p, label, count = counts[i]
            lines.append(f"| {i + 1} | {p} — {label} | {count:,} |")
        lines.extend(["", f"Example: ({example['entity']}, {example['property']}, "
                      f"{example['value']}, {example['frequency']}).", "",
                      f"IDs: {example['entity_id']}, {pid}, {raw_value}. "
                      f"Median start-to-start interval: {example['frequency_days']} days.", "",
                      f"Source: `{example['source']}`.", ""])
    lines.extend(["Label references (retrieved 2026-09-08):", "",
                  "- https://www.wikidata.org/wiki/Q3356809",
                  "- https://www.wikidata.org/wiki/Q178516",
                  "- https://www.wikidata.org/wiki/Q318149", ""])
    (OUTPUT / "Plot 1.5.examples.md").write_text("\n".join(lines), encoding="utf-8")
    (OUTPUT / "Plot 1.5.examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return examples


def main():
    counts, total_rows = load_counts()
    groups = select_groups(counts)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(42, 10), facecolor="white")
    fig.subplots_adjust(left=.035, right=.995, bottom=.22, top=.78)
    colors = ["#3679ad"] * len(counts)
    for _, color, indices in groups:
        for i in indices:
            colors[i] = color
        ax.axvspan(indices[0] - .5, indices[-1] + .5, color=color, alpha=.10, zorder=0)
    bars = ax.bar(range(len(counts)), [r[2] for r in counts], width=.82, color=colors, linewidth=0)
    ax.set_xticks(range(len(counts)), [f"{p} - {label}" for p, label, _ in counts],
                  rotation=90, fontsize=6.5)
    for i, (label, (_, _, count)) in enumerate(zip(ax.get_xticklabels(), counts)):
        if count == 1:
            label.set_bbox({"facecolor": "#fbd0df", "edgecolor": "none", "boxstyle": "square,pad=0.12"})
        if colors[i] != "#3679ad":
            label.set_color(colors[i])
            label.set_fontweight("bold")
    ax.tick_params(axis="x", length=2, pad=3)
    ax.set_xlim(-1, len(counts))
    ax.set_ylim(0, counts[0][2] * 1.16)
    ax.set_xlabel("Property (PID - label), sorted by entity count descending", labelpad=16, fontsize=16)
    ax.set_ylabel("Number of unique entities", fontsize=16)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.annotate(f"{counts[0][2]:,}", (0, counts[0][2]), xytext=(10, 5),
                textcoords="offset points", ha="left", fontsize=12, color=groups[0][1])
    for (name, color, indices), align, card_x in zip(groups, ["left", "center", "right"], [.065, .5, .98]):
        left, right = indices[0] - .48, indices[-1] + .48
        center = (left + right) / 2
        # Exact five-bar span; axes-fraction height keeps tiny groups visible.
        transform = ax.get_xaxis_transform()
        ax.plot([left, left, right, right], [1.005, 1.035, 1.035, 1.005],
                transform=transform, clip_on=False, color=color, linewidth=2.5)
        ax.text(center, 1.060, f"{name} | ranks {indices[0] + 1}–{indices[-1] + 1}",
                transform=transform, ha=align, va="bottom", color=color,
                fontsize=20, fontweight="bold", clip_on=False)
        details = "\n".join(f"{counts[i][0]} — {counts[i][1]}: {counts[i][2]:,}" for i in indices)
        ax.text(card_x, .88, f"{name}\n" + details, transform=ax.transAxes,
                ha="center" if align == "center" else align, va="top", color=color,
                fontsize=15, linespacing=1.7,
                bbox={"facecolor": "white", "edgecolor": color, "alpha": .96,
                      "boxstyle": "round,pad=0.8", "linewidth": 1.2})
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_height = max(t.get_window_extent(renderer).height for t in ax.get_xticklabels()) / fig.dpi
    bottom_inches = max(1.98, label_height + 1.1)
    top_inches = 2.1
    figure_height = bottom_inches + 5.4 + top_inches
    fig.set_size_inches(42, figure_height)
    fig.subplots_adjust(bottom=bottom_inches / figure_height, top=1 - top_inches / figure_height)
    fig.suptitle("Plot 1.5 | Unique entities per property", fontsize=26, y=1 - .36 / figure_height)
    fig.text(.5, 1 - 1.035 / figure_height,
             f"All {len(counts)} properties | {total_rows:,} entity-property pairs | "
             "Before random sampling | Linear y-axis | Ties: numeric PID ascending",
             ha="center", fontsize=16, color="#465565")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assert len(bars) == 379
    for suffix in ("png", "svg"):
        path = OUTPUT / f"Plot 1.5.{suffix}"
        fig.savefig(path, dpi=180, facecolor="white")
        print(f"Saved {path}")
    plt.close(fig)
    for example in write_examples(counts, groups):
        print(json.dumps(example, ensure_ascii=False))


if __name__ == "__main__":
    main()
