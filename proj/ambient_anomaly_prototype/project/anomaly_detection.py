"""
anomaly_detection.py
--------------------
Two complementary layers:

1. Statistical / rule layer  (explainable, addresses the three required scenarios):
     - prolonged daytime inactivity   (>= 6 hours without events between 08:00-20:00)
     - unusual nighttime activity     (event_count between 01:00-04:00 > 2x baseline)
     - missed morning kitchen routine (no kitchen events in the 07:00-08:59 block)

2. Unsupervised model layer  (IsolationForest, contamination=0.05):
     - flags hourly windows whose feature vector is far from the bulk of normal hours
     - complements the rules by catching patterns we did not anticipate

Both layers return an "alerts" DataFrame with: timestamp, type, severity, detail.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


# ------------------------- rule-based detectors ------------------------- #

INACTIVITY_THRESHOLD_HOURS = 6
DAYTIME_HOURS = range(8, 20)            # 08:00 - 19:59
NIGHT_HOURS   = [1, 2, 3]               # 01:00 - 03:59
ROUTINE_HOURS = [7, 8]                  # morning kitchen routine window
NIGHT_RATIO_THRESHOLD = 2.0             # 200% of nighttime baseline


def detect_prolonged_inactivity(feats: pd.DataFrame) -> pd.DataFrame:
    """Trigger when inactivity_hours crosses the threshold during the daytime."""
    daytime = feats[feats["hour"].isin(DAYTIME_HOURS)]
    triggered = daytime[daytime["inactivity_hours"] >= INACTIVITY_THRESHOLD_HOURS]

    # only emit one alert per uninterrupted inactivity streak (the peak hour)
    if triggered.empty:
        return pd.DataFrame(columns=["timestamp", "type", "severity", "detail"])

    alerts = []
    last_alert_date = None
    for _, row in triggered.iterrows():
        # de-duplicate: one alert per (date, streak)
        if row["date"] == last_alert_date:
            continue
        last_alert_date = row["date"]
        alerts.append({
            "timestamp": row["hour_bin"],
            "type":      "prolonged_inactivity",
            "severity":  "medium",
            "detail":    f"{int(row['inactivity_hours'])}h without sensor events "
                         f"(daytime, threshold {INACTIVITY_THRESHOLD_HOURS}h)",
        })
    return pd.DataFrame(alerts)


def detect_nighttime_activity(feats: pd.DataFrame) -> pd.DataFrame:
    """Flag nights where 01:00-04:00 activity exceeds 200% of the personal baseline."""
    night = feats[feats["hour"].isin(NIGHT_HOURS)]
    if night.empty:
        return pd.DataFrame(columns=["timestamp", "type", "severity", "detail"])

    baseline = night["event_count"].mean()
    if baseline == 0:
        baseline = 0.5  # avoid div-by-zero; small floor

    nightly = night.groupby("date")["event_count"].sum().reset_index()
    nightly_baseline = baseline * len(NIGHT_HOURS)
    nightly["ratio"] = nightly["event_count"] / max(nightly_baseline, 1.0)

    alerts = []
    for _, row in nightly[nightly["ratio"] >= NIGHT_RATIO_THRESHOLD].iterrows():
        ts = pd.Timestamp(row["date"]) + pd.Timedelta(hours=2)
        alerts.append({
            "timestamp": ts,
            "type":      "unusual_nighttime_activity",
            "severity":  "low",
            "detail":    f"{int(row['event_count'])} events during 01:00-04:00 "
                         f"(~{row['ratio']:.1f}x baseline)",
        })
    return pd.DataFrame(alerts)


def detect_missed_routine(feats: pd.DataFrame) -> pd.DataFrame:
    """Flag days where the 07:00-08:59 kitchen window is empty but other days have it."""
    morning = feats[feats["hour"].isin(ROUTINE_HOURS)]
    daily_kitchen = morning.groupby("date")["kitchen_events"].sum().reset_index()

    if daily_kitchen.empty:
        return pd.DataFrame(columns=["timestamp", "type", "severity", "detail"])

    # establish "normal" days as those with any morning kitchen activity
    normal_days = (daily_kitchen["kitchen_events"] > 0).sum()
    if normal_days < 5:
        return pd.DataFrame(columns=["timestamp", "type", "severity", "detail"])

    missed = daily_kitchen[daily_kitchen["kitchen_events"] == 0]
    alerts = []
    for _, row in missed.iterrows():
        ts = pd.Timestamp(row["date"]) + pd.Timedelta(hours=8)
        alerts.append({
            "timestamp": ts,
            "type":      "missed_morning_routine",
            "severity":  "medium",
            "detail":    "no kitchen activity 07:00-09:00 "
                         "(typical morning routine absent)",
        })
    return pd.DataFrame(alerts)


# ---------------------- unsupervised model layer ------------------------ #

# features used by the per-hour IsolationForest (we strip 'hour' and 'is_night'
# because each model is already conditioned on a single hour-of-day)
MODEL_FEATURE_COLS = [
    "event_count", "unique_sensors",
    "kitchen_events", "bedroom_events", "bath_events",
    "living_events", "hall_events", "door_events",
    "max_gap_min", "inactivity_hours",
]


@dataclass
class ModelAlerts:
    models: dict          # hour -> IsolationForest
    scored: pd.DataFrame  # feats + ['anomaly_score', 'is_anomaly']
    alerts: pd.DataFrame  # subset for display


def run_isolation_forest(feats: pd.DataFrame, contamination: float = 0.05) -> ModelAlerts:
    """
    Train one IsolationForest per hour-of-day, so anomalies are judged
    relative to the same hour on other days. This avoids the trivial
    "07:00 is busy" false positives a global model would generate.
    """
    scored = feats.copy()
    scored["anomaly_score"] = 0.0
    scored["is_anomaly"]    = False
    models: dict = {}

    for hour, group in feats.groupby("hour"):
        if len(group) < 5:
            continue  # too few samples to fit a meaningful model
        X = group[MODEL_FEATURE_COLS].values
        model = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42,
        )
        model.fit(X)
        models[int(hour)] = model

        idx = group.index
        scored.loc[idx, "anomaly_score"] = -model.score_samples(X)
        scored.loc[idx, "is_anomaly"]    = model.predict(X) == -1

    alerts_df = scored[scored["is_anomaly"]].copy()
    alerts_df = alerts_df.rename(columns={"hour_bin": "timestamp"})
    alerts_df["type"]     = "model_anomaly"
    alerts_df["severity"] = "info"
    alerts_df["detail"]   = alerts_df.apply(
        lambda r: f"IsolationForest score={r['anomaly_score']:.2f} "
                  f"(unusual for hour {int(r['hour']):02d}:00, "
                  f"events={int(r['event_count'])})",
        axis=1,
    )
    alerts_df = alerts_df[["timestamp", "type", "severity", "detail"]]
    return ModelAlerts(models=models, scored=scored, alerts=alerts_df)


# ----------------------------- orchestrator ----------------------------- #

ALERT_COOLDOWN = pd.Timedelta(hours=4)


def suppress_duplicate_alerts(alerts: pd.DataFrame) -> pd.DataFrame:
    """Keep only one alert of the same type per cooldown window."""
    if alerts.empty:
        return alerts
    alerts = alerts.sort_values("timestamp").reset_index(drop=True)
    keep = []
    last_seen: dict[str, pd.Timestamp] = {}
    for _, row in alerts.iterrows():
        prev = last_seen.get(row["type"])
        if prev is None or (row["timestamp"] - prev) >= ALERT_COOLDOWN:
            keep.append(row)
            last_seen[row["type"]] = row["timestamp"]
    return pd.DataFrame(keep).reset_index(drop=True)


def detect_all(feats: pd.DataFrame, contamination: float = 0.05):
    rule_alerts = pd.concat([
        detect_prolonged_inactivity(feats),
        detect_nighttime_activity(feats),
        detect_missed_routine(feats),
    ], ignore_index=True)

    model_out = run_isolation_forest(feats, contamination=contamination)

    all_alerts = pd.concat([rule_alerts, model_out.alerts], ignore_index=True)
    all_alerts = suppress_duplicate_alerts(all_alerts)
    return all_alerts, model_out


if __name__ == "__main__":
    import os
    from preprocessing import load_events, hourly_features

    here = os.path.dirname(os.path.abspath(__file__))
    events = load_events(os.path.join(here, "data", "sensor_events.csv"))
    feats  = hourly_features(events)

    alerts, model_out = detect_all(feats)
    print(f"Total alerts: {len(alerts)}")
    print(alerts.to_string(index=False))
