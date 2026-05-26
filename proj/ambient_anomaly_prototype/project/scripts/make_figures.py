"""
make_figures.py
---------------
Generate static figures saved to dashboard/ for use in the report and paper.
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import matplotlib.pyplot as plt

from preprocessing import load_events, hourly_features
from anomaly_detection import detect_all


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "sensor_events.csv")
OUT  = os.path.join(HERE, "dashboard")
os.makedirs(OUT, exist_ok=True)


SEVERITY_COLOR = {"low": "#f4c542", "medium": "#e07b39", "high": "#c0392b", "info": "#5b8def"}


def main():
    events = load_events(DATA)
    feats  = hourly_features(events)
    alerts, _ = detect_all(feats)

    # --- Figure 1: full timeline with alerts overlaid ----------------------
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.plot(feats["hour_bin"], feats["event_count"], linewidth=0.8, color="#5b8def")
    ax.fill_between(feats["hour_bin"], 0, feats["event_count"], alpha=0.18, color="#5b8def")
    for _, row in alerts.iterrows():
        ax.axvline(row["timestamp"],
                   color=SEVERITY_COLOR.get(row["severity"], "#888"),
                   alpha=0.6, linewidth=1.2)
    ax.set_title("Hourly sensor activity over 30 days (vertical lines = alerts)")
    ax.set_xlabel("date"); ax.set_ylabel("events / hour")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "timeline.png"), dpi=140)
    plt.close(fig)

    # --- Figure 2: last-3-day zoom showing the three anomalies -------------
    last3 = feats[feats["date"] >= pd.Timestamp("2026-01-28").date()]
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.bar(last3["hour_bin"], last3["event_count"], width=0.035,
           color="#5b8def", alpha=0.85)
    for _, row in alerts.iterrows():
        if row["timestamp"].date() < pd.Timestamp("2026-01-28").date():
            continue
        ax.axvline(row["timestamp"],
                   color=SEVERITY_COLOR.get(row["severity"], "#888"),
                   alpha=0.7, linewidth=1.5)
    ax.set_title("Last 3 days: injected anomalies and detector alerts")
    ax.set_xlabel("time"); ax.set_ylabel("events / hour")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "anomaly_days.png"), dpi=140)
    plt.close(fig)

    # --- Figure 3: hour-of-day baseline -----------------------------------
    by_hour = feats.groupby("hour")["event_count"].agg(["mean", "std"]).reset_index()
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.bar(by_hour["hour"], by_hour["mean"], yerr=by_hour["std"],
           color="#5b8def", alpha=0.75, capsize=3)
    ax.set_title("Average events per hour-of-day (with ±1 std)")
    ax.set_xlabel("hour of day"); ax.set_ylabel("mean events / hour")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "hour_baseline.png"), dpi=140)
    plt.close(fig)

    print(f"Wrote 3 figures to {OUT}")


if __name__ == "__main__":
    main()
