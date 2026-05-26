"""
preprocessing.py
----------------
Load raw sensor events and turn them into compact hourly feature rows.

We keep features deliberately simple and explainable:

  hour            : hour of day (0-23), preserved as a feature
  is_night        : 1 if hour in [0,1,2,3,4,5], else 0
  event_count     : number of sensor firings in the hour
  unique_sensors  : distinct sensors active in the hour
  kitchen_events  : motion+fridge events in the kitchen
  bedroom_events  : bedroom motion + bed pressure
  bath_events     : bath motion
  living_events   : living motion + sofa pressure
  hall_events     : hall motion
  door_events     : entrance door openings
  inactivity_min  : minutes since the previous event (carried into this hour)

Aggregation window: 1 hour. Smaller windows (15 / 30 min) are easy drop-in
replacements if needed.
"""

from __future__ import annotations
import pandas as pd


KITCHEN = {"MOTION_KITCHEN", "DOOR_FRIDGE"}
BEDROOM = {"MOTION_BEDROOM", "PRESSURE_BED"}
BATH    = {"MOTION_BATH"}
LIVING  = {"MOTION_LIVING", "PRESSURE_SOFA"}
HALL    = {"MOTION_HALL"}
DOOR    = {"DOOR_ENTRANCE"}


def load_events(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _room_count(group: pd.Series, members: set) -> int:
    return int(group.isin(members).sum())


def hourly_features(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate event rows into one row per (day, hour)."""
    df = events.copy()
    df["hour_bin"] = df["timestamp"].dt.floor("h")

    # gap to previous event, in minutes
    df["gap_min"] = df["timestamp"].diff().dt.total_seconds().div(60).fillna(0)

    # build a continuous hourly index across the full observed range
    start = df["hour_bin"].min()
    end   = df["hour_bin"].max()
    full_index = pd.date_range(start, end, freq="h")

    rows = []
    for hour_bin, group in df.groupby("hour_bin"):
        rows.append({
            "hour_bin":       hour_bin,
            "event_count":    len(group),
            "unique_sensors": group["sensor_id"].nunique(),
            "kitchen_events": _room_count(group["sensor_id"], KITCHEN),
            "bedroom_events": _room_count(group["sensor_id"], BEDROOM),
            "bath_events":    _room_count(group["sensor_id"], BATH),
            "living_events":  _room_count(group["sensor_id"], LIVING),
            "hall_events":    _room_count(group["sensor_id"], HALL),
            "door_events":    _room_count(group["sensor_id"], DOOR),
            "max_gap_min":    float(group["gap_min"].max()),
        })

    feats = pd.DataFrame(rows).set_index("hour_bin")
    # reindex to fill empty hours with zero activity
    feats = feats.reindex(full_index, fill_value=0)
    feats.index.name = "hour_bin"
    feats = feats.reset_index()

    feats["hour"]     = feats["hour_bin"].dt.hour
    feats["is_night"] = feats["hour"].isin([0, 1, 2, 3, 4, 5]).astype(int)
    feats["date"]     = feats["hour_bin"].dt.date

    # rolling inactivity: longest stretch of zero-event hours ending at this hour
    inactivity = []
    streak = 0
    for c in feats["event_count"]:
        streak = streak + 1 if c == 0 else 0
        inactivity.append(streak)
    feats["inactivity_hours"] = inactivity

    return feats


FEATURE_COLS = [
    "event_count", "unique_sensors",
    "kitchen_events", "bedroom_events", "bath_events",
    "living_events", "hall_events", "door_events",
    "max_gap_min", "is_night", "inactivity_hours",
]


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    df = load_events(os.path.join(here, "data", "sensor_events.csv"))
    feats = hourly_features(df)
    print(f"{len(feats)} hourly rows, columns: {list(feats.columns)}")
    print(feats.head(10))
