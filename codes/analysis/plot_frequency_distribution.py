"""Plot the pre-sampling population; do not recalculate or modify its labels.

Run: python codes/analysis/plot_frequency_distribution.py
Outputs: data/analysis/frequency_before_sampling (PNG, PDF, CSV, JSON).
Only matplotlib and numpy are required. Every timeline is counted once, and
counts are cross-checked against the matching collection manifest.
"""

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"
MANIFEST = ROOT / "data/raw/wd_scan/qlever_manifest.before_overlapfix.json"
OUT = ROOT / "data/analysis/frequency_before_sampling"
CLASSES = ["A-Day", "A-Few-Days", "A-Week", "A-Few-Weeks", "A-Month",
           "A-Few-Months", "A-Year", "A-Few-Years", "Many-Years"]
SHORT = ["Day", "Few days", "Week", "Few weeks", "Month",
         "Few months", "Year", "Few years", "Many years"]
DEFINITION = "Existing labels: median of positive consecutive START-to-START gaps; before overlap fix."


def main():
    manifest = json.loads(MANIFEST.read_text())
    pids = sorted((p.stem for p in SOURCE.glob("*.jsonl")), key=lambda p: int(p[1:]))
    matrix = np.zeros((len(pids), len(CLASSES)), dtype=int)
    for i, pid in enumerate(pids):
        seen = set()
        with (SOURCE / (pid + ".jsonl")).open() as stream:
            for line in stream:
                row = json.loads(line)
                key = (row["subject"], row["property"])
                if key in seen:
                    raise ValueError("Duplicate timeline: " + str(key))
                seen.add(key)
                assert row["property"] == pid
                matrix[i, CLASSES.index(row["frequency_class"])] += 1
        expected = [manifest[pid]["classes"][c] for c in CLASSES]
        if matrix[i].tolist() != expected:
            raise ValueError("Manifest disagreement: " + pid)
    class_n = matrix.sum(axis=0)
    relation_n = matrix.sum(axis=1)
    total = int(matrix.sum())
    assert total == sum(r.get("n_valid", 0) for r in manifest.values())
    labels = [manifest[p]["label"] for p in pids]
    rank = np.argsort(-relation_n, kind="stable")
    expected = relation_n[:, None] * class_n[None, :] / total
    chi2 = np.sum((matrix - expected) ** 2 / expected)
    v = float(np.sqrt(chi2 / (total * min(matrix.shape[0] - 1, matrix.shape[1] - 1))))
    row_pct = matrix / relation_n[:, None] * 100
    col_pct = matrix / class_n[None, :] * 100
    lift = matrix / expected
    OUT.mkdir(parents=True, exist_ok=True)

    with (OUT / "relation_frequency.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["relation", "relation_label", "frequency", "count",
                         "pct_within_relation", "pct_within_class", "lift"])
        for i in rank:
            for j, cls in enumerate(CLASSES):
                writer.writerow([pids[i], labels[i], cls, int(matrix[i, j]),
                                 float(row_pct[i, j]), float(col_pct[i, j]), float(lift[i, j])])
    summary = {
        "source": str(SOURCE), "definition": DEFINITION,
        "sampling_unit": "entity_property_timeline", "total": total,
        "properties_scanned": len(manifest), "valid_properties": len(pids),
        "class_counts": dict(zip(CLASSES, map(int, class_n))),
        "cramers_v": v,
        "association_note": "Descriptive association in the filtered population, not causation; no p-value. Sparse cells exist.",
        "top_relations": [{"pid": pids[i], "label": labels[i], "n": int(relation_n[i])}
                          for i in rank[:12]],
        "top_relation_per_class": [
            {"class": c, "label": labels[int(matrix[:, j].argmax())],
             "n": int(matrix[:, j].max()), "share_pct": float(col_pct[:, j].max())}
            for j, c in enumerate(CLASSES)],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    colors = ["#e46b38", "#3579b1", "#4b9b7b", "#9774af", "#b69537", "#50a7b2"]
    # Shared category palette, with detention placed first for easy comparison.
    detention = pids.index("P2632")
    selected = [detention] + [int(i) for i in rank if i != detention][:5]
    fig, axes = plt.subplots(1, 2, figsize=(17, 7), gridspec_kw={"width_ratios": [1, 1.35]})
    fig.subplots_adjust(left=.10, right=.98, top=.82, bottom=.22, wspace=.32)
    fig.suptitle("Before random sampling: where are the timelines concentrated?", fontsize=19, y=.97)
    fig.text(.5, .91, f"{total:,} timelines | {len(pids):,} relations | {len(manifest):,} properties scanned", ha="center")
    fig.text(.5, .865, DEFINITION, ha="center", fontsize=10, color="#555555")
    y = np.arange(len(CLASSES))
    ax = axes[0]
    ax.barh(y, class_n, color="#3579b1", height=.66)
    ax.set_yticks(y, CLASSES)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(1, max(class_n) * 8)
    ax.set_xlabel("Timeline count (log scale)")
    ax.set_title("1. Frequency class sizes", loc="left", pad=15, fontweight="bold")
    ax.grid(axis="x", alpha=.15)
    ax.set_axisbelow(True)
    for j, n in enumerate(class_n):
        ax.text(n * 1.12, j, f"{n:,}  ({100*n/total:.2f}%)", va="center", fontsize=9)
    ax = axes[1]
    left = np.zeros(len(CLASSES))
    for i, color in zip(selected, colors):
        vals = col_pct[i]
        ax.barh(y, vals, left=left, color=color, label=labels[i], height=.66)
        for j, val in enumerate(vals):
            if val >= 12:
                ax.text(left[j]+val/2, j, f"{val:.0f}%", ha="center", va="center", color="white", fontsize=9)
        left += vals
    ax.barh(y, 100-left, left=left, color="#cbd0d5", label="Other relations", height=.66)
    ax.set_yticks(y, SHORT)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share within each frequency class (%)")
    ax.set_title("2. Which relations make up each class?", loc="left", pad=15, fontweight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.13), ncol=2, frameon=False, fontsize=9)
    fig.text(.10, .035, "Each row in panel 2 sums to 100%. Day has only 20 timelines; its composition is based on very little data.", fontsize=10)
    fig.savefig(OUT / "01_class_distribution.png", dpi=180)

    # Show large relations and class-specific leaders, without hiding all rare-class signals.
    chosen = set(map(int, rank[:12]))
    for j in range(len(CLASSES)):
        for i in np.argsort(-matrix[:, j], kind="stable")[:3]:
            if matrix[i, j] >= 5:
                chosen.add(int(i))
    chosen = sorted(chosen, key=lambda i: (-relation_n[i], int(pids[i][1:])))
    nrows = len(chosen)
    fig2, axes2 = plt.subplots(1, 2, figsize=(20, max(9, nrows * .42 + 3)))
    fig2.subplots_adjust(left=.24, right=.97, bottom=.20, top=.82, wspace=.18)
    fig2.suptitle("Relation and frequency: concentration versus enrichment", fontsize=20, y=.975)
    fig2.text(.5, .929, f"Cramer's V = {v:.3f} across all {len(pids)} relations (descriptive categorical association; not causation)", ha="center")
    fig2.text(.5, .89, DEFINITION, ha="center", fontsize=10, color="#555555")
    shown = row_pct[chosen]
    img = axes2[0].imshow(shown, aspect="auto", cmap="Blues", vmin=0, vmax=100)
    for r in range(nrows):
        for c in range(9):
            val = shown[r, c]
            if val >= .5:
                axes2[0].text(c, r, f"{val:.0f}", ha="center", va="center", fontsize=8,
                              color="white" if val > 55 else "#28323c")
    axes2[0].set_title("3. Frequency distribution within each relation (%)", loc="left", pad=15, fontweight="bold")
    axes2[0].set_yticks(range(nrows), [f"{labels[i]} ({pids[i]})  n={relation_n[i]:,}" for i in chosen], fontsize=9)
    cb = fig2.colorbar(img, ax=axes2[0], orientation="horizontal", pad=.15, fraction=.04)
    cb.set_label("Each row sums to 100%; annotations rounded to whole percentages")
    # Lift separates class association from the unequal class sizes.
    loglift = np.full((nrows, 9), np.nan)
    positive = matrix[chosen] > 0
    loglift[positive] = np.log2(lift[chosen][positive])
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("#dddddd")
    img2 = axes2[1].imshow(np.ma.masked_invalid(loglift), aspect="auto", cmap=cmap, vmin=-4, vmax=4)
    axes2[1].set_yticks(range(nrows), [""] * nrows)
    axes2[1].set_title("4. More or less common than the overall baseline?", loc="left", pad=15, fontweight="bold")
    for r, i in enumerate(chosen):
        for c in range(9):
            if matrix[i, c] >= 5:
                val = lift[i, c]
                axes2[1].text(c, r, f"{val:.1f}x", ha="center", va="center", fontsize=7,
                              color="white" if abs(loglift[r, c]) > 2.5 else "#28323c")
    cb2 = fig2.colorbar(img2, ax=axes2[1], orientation="horizontal", pad=.15, fraction=.04, extend="both")
    cb2.set_ticks([-4, -2, 0, 2, 4], ["1/16x", "1/4x", "1x", "4x", "16x"])
    cb2.set_label("Lift = P(class | relation) / P(class); color uses log2(lift), clipped at 1/16x and 16x")
    for ax in axes2:
        ax.set_xticks(range(9), SHORT, rotation=40, ha="right", fontsize=9)
        ax.set_xticks(np.arange(-.5, 9, 1), minor=True)
        ax.set_yticks(np.arange(-.5, nrows, 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=.7)
        ax.tick_params(which="minor", bottom=False, left=False)
    fig2.text(.24, .04, "Gray = zero observations. Lift annotations require count >= 5; sparse colored cells remain exploratory.\nRows: top 12 relations overall plus top 3 in each class with count >= 5. Full 379-relation table is in the CSV.", fontsize=10)
    fig2.savefig(OUT / "02_relation_frequency.png", dpi=180)
    with PdfPages(OUT / "frequency_distribution.pdf") as pdf:
        pdf.savefig(fig)
        pdf.savefig(fig2)
    plt.close("all")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("Plots and tables:", OUT)


if __name__ == "__main__":
    main()

