"""Plot daily frequency bins using unique entities within each bin.

Run: python codes/analysis/plot4.py
Uses the original pre-sampling population and its stored median_interval_days.
Bins are [day, day + 1); an entity can occur in multiple bins via different
properties. No error bars: these are observed counts, not estimated means.
"""

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullLocator, StrMethodFormatter

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
OUTPUT = ROOT / "data/analysis/plot/plot4"


def main():
    manifest = json.loads((SOURCE.parent / "qlever_manifest.before_overlapfix.json").read_text())
    entities_by_day = defaultdict(set)
    timeline_counts = Counter()
    entities = set()
    frequencies = []
    maximum_record = None
    for path in sorted(SOURCE.glob("P*.jsonl"), key=lambda p: int(p.stem[1:])):
        seen = set()
        classes = Counter()
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                subject = row["subject"]
                if row["property"] != path.stem or subject in seen:
                    raise ValueError(f"Duplicate or mismatched timeline: {path}")
                seen.add(subject)
                days = float(row["median_interval_days"])
                if not math.isfinite(days) or days < 1:
                    raise ValueError(f"Unexpected frequency: {days}")
                day = math.floor(days)
                entities_by_day[day].add(subject)
                timeline_counts[day] += 1
                entities.add(subject)
                frequencies.append(days)
                classes[row["frequency_class"]] += 1
                if maximum_record is None or days > maximum_record["frequency_days"]:
                    maximum_record = {"subject": subject, "property": row["property"],
                                      "frequency_days": days}
        if classes != Counter(manifest[path.stem]["classes"]):
            raise ValueError(f"Manifest mismatch: {path}")
    if len(frequencies) != 151_547:
        raise ValueError(f"Unexpected population: {len(frequencies)}")

    max_days = max(frequencies)
    # Preserve every empty daily bin without allocating 1.3 million rectangles.
    edges = sorted({1, math.floor(max_days) + 1} |
                   {edge for day in entities_by_day for edge in (day, day + 1)})
    counts = [len(entities_by_day.get(day, ())) for day in edges[:-1]]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(13, 6.5), facecolor="white")
    fig.subplots_adjust(left=.11, right=.92, top=.83, bottom=.19)
    ax.stairs(counts, edges, fill=True, color="#3679ad", linewidth=.8)
    # Daily bins become sub-pixel-wide on a log axis; retain visible count spikes.
    ax.vlines([day + .5 for day in entities_by_day], 0,
              [len(subjects) for subjects in entities_by_day.values()],
              color="#3679ad", linewidth=.65)
    ax.set_xscale("log")
    ax.set_xlim(1, edges[-1])
    ticks = [1, 10, 100, 1_000, 10_000, 100_000, max_days]
    ax.set_xticks(ticks, [f"{x:,.0f}" for x in ticks])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.set_ylim(0, max(counts) * 1.12)
    ax.set_xlabel("Frequency (days; log scale)", labelpad=13, fontsize=13)
    ax.set_ylabel("# of entities", labelpad=10, fontsize=13)
    ax.set_title("plot4 | Entity counts by frequency", fontsize=17, pad=40)
    ax.text(.5, 1.025, f"1-day bins | Unique entities within each bin | Max: {max_days:,.0f} days",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=11)
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg"):
        path = OUTPUT / f"plot4.{suffix}"
        fig.savefig(path, dpi=180, facecolor="white")
        print(f"Saved {path}")
    plt.close(fig)
    with (OUTPUT / "plot4.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["day_start_inclusive", "day_end_exclusive", "unique_entities", "entity_property_timelines"])
        for day in sorted(entities_by_day):
            writer.writerow([day, day + 1, len(entities_by_day[day]), timeline_counts[day]])
    summary = {
        "source": str(SOURCE), "total_timelines": len(frequencies),
        "unique_entities_overall": len(entities),
        "frequency_definition": "Stored median of positive consecutive start-to-start intervals, in days.",
        "min_frequency_days": min(frequencies), "max_frequency_days": max_days,
        "maximum_record": maximum_record,
        "bin_definition": "[day, day + 1); fractional medians are assigned without changing source values.",
        "y_definition": "Distinct subject QIDs per daily bin; entities may occur in multiple bins via different properties.",
        "sum_of_bin_entity_counts": sum(counts),
        "csv_note": "Only nonzero bins are listed; all omitted days have zero observations.",
        "x_scale": "log", "y_scale": "linear",
        "error_bars": "None: descriptive counts of the observed population, no uncertainty model.",
    }
    (OUTPUT / "plot4.meta.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
