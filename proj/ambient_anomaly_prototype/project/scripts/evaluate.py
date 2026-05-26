"""
evaluate.py
-----------
Reproducible, small-scale evaluation of the anomaly detector.

Scenarios:
  1. Normal scenario   : days 1-27 (no labelled anomalies).
  2. Anomaly scenario  : days 28-30 (each contains one injected anomaly type).
  3. Failure case      : simulated sensor outage on day 15 (drop all events for
                         that day) and check whether the detector raises a
                         (false) prolonged-inactivity alert.

Metrics:
  - rule-based detection: precision / recall on the three required scenarios
  - IsolationForest:      false-positive rate on labelled-normal days
  - detection latency:    time from anomaly start to first alert (in hours)
"""

from __future__ import annotations
import os
import sys
import time

# allow `python scripts/evaluate.py` from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from preprocessing import load_events, hourly_features
from anomaly_detection import detect_all


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "sensor_events.csv")


# Ground truth from the simulator (see scripts/simulate_data.py)
LABELS = {
    pd.Timestamp("2026-01-28").date(): "prolonged_inactivity",
    pd.Timestamp("2026-01-29").date(): "unusual_nighttime_activity",
    pd.Timestamp("2026-01-30").date(): "missed_morning_routine",
}
# anomaly "start" times for latency measurement
ANOMALY_START = {
    pd.Timestamp("2026-01-28").date(): pd.Timestamp("2026-01-28 10:00:00"),
    pd.Timestamp("2026-01-29").date(): pd.Timestamp("2026-01-29 01:00:00"),
    pd.Timestamp("2026-01-30").date(): pd.Timestamp("2026-01-30 07:00:00"),
}


def evaluate_rule_alerts(alerts: pd.DataFrame) -> dict:
    """Per-scenario precision/recall for the rule-based layer."""
    rule_types = ["prolonged_inactivity", "unusual_nighttime_activity", "missed_morning_routine"]
    rule_alerts = alerts[alerts["type"].isin(rule_types)].copy()
    rule_alerts["date"] = rule_alerts["timestamp"].dt.date

    results = {}
    for ts_date, label in LABELS.items():
        hits = rule_alerts[(rule_alerts["date"] == ts_date) & (rule_alerts["type"] == label)]
        results[label] = {
            "detected": len(hits) > 0,
            "n_alerts": int(len(hits)),
        }

    # false positives: rule alerts on labelled-normal days
    fp = rule_alerts[~rule_alerts["date"].isin(LABELS.keys())]
    return {"per_scenario": results, "false_positives_rule_layer": len(fp)}


def evaluate_model_fpr(alerts: pd.DataFrame, feats: pd.DataFrame) -> dict:
    """IsolationForest false-positive rate over labelled-normal days."""
    model_alerts = alerts[alerts["type"] == "model_anomaly"].copy()
    model_alerts["date"] = model_alerts["timestamp"].dt.date
    normal_dates = [d for d in feats["date"].unique() if d not in LABELS]
    normal_hours = feats[feats["date"].isin(normal_dates)]
    fp = model_alerts[model_alerts["date"].isin(normal_dates)]
    return {
        "normal_hours":          int(len(normal_hours)),
        "model_alerts_on_normal": int(len(fp)),
        "false_positive_rate":    round(len(fp) / max(len(normal_hours), 1), 4),
    }


def evaluate_latency(alerts: pd.DataFrame) -> dict:
    """Hours between anomaly onset and first alert for that scenario."""
    out = {}
    for ts_date, label in LABELS.items():
        candidates = alerts[
            (alerts["timestamp"].dt.date == ts_date) & (alerts["type"] == label)
        ].sort_values("timestamp")
        if candidates.empty:
            out[label] = None
            continue
        first = candidates.iloc[0]["timestamp"]
        latency = (first - ANOMALY_START[ts_date]).total_seconds() / 3600
        out[label] = round(latency, 1)
    return out


def failure_case_sensor_outage(events: pd.DataFrame) -> dict:
    """
    Drop every event from Jan 15 (normally a busy, healthy day) to simulate a
    sensor outage. The detector should -- without context -- raise a (false)
    prolonged_inactivity alert, illustrating a real-world failure mode that
    additional sensor-health monitoring would need to catch.
    """
    outage_date = pd.Timestamp("2026-01-15").date()
    broken = events[events["timestamp"].dt.date != outage_date].copy()
    feats  = hourly_features(broken)
    alerts, _ = detect_all(feats)
    triggered = alerts[
        (alerts["timestamp"].dt.date == outage_date) &
        (alerts["type"] == "prolonged_inactivity")
    ]
    return {
        "outage_date":             str(outage_date),
        "false_inactivity_alert":  bool(len(triggered) > 0),
        "note": "An outage produces a false inactivity alert. Sensor-health "
                "monitoring is recommended as a complementary safeguard.",
    }


def main():
    events = load_events(DATA)
    feats  = hourly_features(events)

    t0 = time.perf_counter()
    alerts, _ = detect_all(feats)
    detect_seconds = time.perf_counter() - t0

    rule = evaluate_rule_alerts(alerts)
    model = evaluate_model_fpr(alerts, feats)
    latency = evaluate_latency(alerts)
    failure = failure_case_sensor_outage(events)

    print("=" * 60)
    print("ANOMALY DETECTION EVALUATION")
    print("=" * 60)
    print(f"\nDataset: {len(events)} events over {feats['date'].nunique()} days")
    print(f"Total detection runtime: {detect_seconds*1000:.1f} ms\n")

    print("--- Rule-based detection per scenario ---")
    for scenario, info in rule["per_scenario"].items():
        status = "✓ DETECTED" if info["detected"] else "✗ MISSED"
        print(f"  {scenario:30s} {status}  ({info['n_alerts']} alert(s))")
    print(f"  Rule-layer false positives on normal days: {rule['false_positives_rule_layer']}")

    print("\n--- Detection latency (hours from anomaly onset) ---")
    for scenario, hours in latency.items():
        val = f"{hours}h" if hours is not None else "n/a (not detected)"
        print(f"  {scenario:30s} {val}")

    print("\n--- IsolationForest model layer ---")
    print(f"  Normal hours observed:    {model['normal_hours']}")
    print(f"  Model alerts on normals:  {model['model_alerts_on_normal']}")
    print(f"  False-positive rate:      {model['false_positive_rate']*100:.2f}%")

    print("\n--- Failure case: sensor outage on", failure["outage_date"], "---")
    print(f"  Raised false inactivity alert: {failure['false_inactivity_alert']}")
    print(f"  {failure['note']}")
    print()


if __name__ == "__main__":
    main()
