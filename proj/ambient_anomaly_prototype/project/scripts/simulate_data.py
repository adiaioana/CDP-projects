"""
simulate_data.py
----------------
Generate a small CASAS-style ambient sensor dataset for a single-resident home.

The simulator models a normal daily routine across 30 days, then injects three
anomaly types on the final 3 days so we can test detection:

  Day 28: prolonged daytime inactivity (no motion 10:00-17:00)
  Day 29: unusual nighttime movement   (high activity 01:00-04:00)
  Day 30: missed morning routine       (no kitchen activity at 07:00-08:00)

Output: data/sensor_events.csv with columns: timestamp, sensor_id, event
Privacy: sensor IDs are anonymized room/device tags. No identity, audio, or
video data is generated or stored.
"""

import os
import random
from datetime import datetime, timedelta

import pandas as pd

RNG = random.Random(42)

SENSORS = {
    "MOTION_BEDROOM": "ON",
    "MOTION_KITCHEN": "ON",
    "MOTION_LIVING":  "ON",
    "MOTION_BATH":    "ON",
    "MOTION_HALL":    "ON",
    "DOOR_FRIDGE":    "OPEN",
    "DOOR_ENTRANCE":  "OPEN",
    "PRESSURE_BED":   "ON",
    "PRESSURE_SOFA":  "ON",
}


def jitter(base_minute: int, spread: int = 10) -> int:
    """Return base_minute +/- spread, clamped to [0, 59]."""
    return max(0, min(59, base_minute + RNG.randint(-spread, spread)))


def emit(events, day: datetime, hour: int, minute: int, sensor: str):
    ts = day.replace(hour=hour, minute=minute, second=RNG.randint(0, 59))
    events.append((ts, sensor, SENSORS[sensor]))


def normal_day(events, day: datetime):
    """A typical day: wake -> kitchen -> bath -> living -> kitchen -> bed."""
    # 06:30-07:30 wake up
    emit(events, day, 6, jitter(45), "PRESSURE_BED")
    emit(events, day, 7, jitter(0), "MOTION_BEDROOM")
    emit(events, day, 7, jitter(5), "MOTION_HALL")

    # 07:00-08:30 breakfast
    for _ in range(RNG.randint(4, 7)):
        emit(events, day, 7, jitter(30), "MOTION_KITCHEN")
    emit(events, day, 7, jitter(35), "DOOR_FRIDGE")
    emit(events, day, 8, jitter(0), "MOTION_KITCHEN")

    # 08:30-09:30 bath
    emit(events, day, 8, jitter(45), "MOTION_BATH")
    emit(events, day, 9, jitter(0), "MOTION_BATH")

    # 09:30-12:00 living room
    for _ in range(RNG.randint(5, 9)):
        h = RNG.choice([9, 10, 11])
        emit(events, day, h, jitter(30, 25), "MOTION_LIVING")
    emit(events, day, 10, jitter(0), "PRESSURE_SOFA")

    # 12:00-13:00 lunch
    for _ in range(RNG.randint(3, 6)):
        emit(events, day, 12, jitter(20), "MOTION_KITCHEN")
    emit(events, day, 12, jitter(15), "DOOR_FRIDGE")

    # 13:00-17:00 mixed living/light activity
    for _ in range(RNG.randint(6, 12)):
        h = RNG.choice([13, 14, 15, 16])
        emit(events, day, h, jitter(30, 25), RNG.choice(["MOTION_LIVING", "PRESSURE_SOFA", "MOTION_HALL"]))

    # 17:00-18:00 maybe go out
    if RNG.random() < 0.3:
        emit(events, day, 17, jitter(30), "DOOR_ENTRANCE")
        emit(events, day, 18, jitter(30), "DOOR_ENTRANCE")

    # 18:00-20:00 dinner
    for _ in range(RNG.randint(5, 9)):
        h = RNG.choice([18, 19])
        emit(events, day, h, jitter(30, 25), "MOTION_KITCHEN")
    emit(events, day, 18, jitter(45), "DOOR_FRIDGE")

    # 20:00-22:30 evening living
    for _ in range(RNG.randint(6, 10)):
        h = RNG.choice([20, 21, 22])
        emit(events, day, h, jitter(30, 25), RNG.choice(["MOTION_LIVING", "PRESSURE_SOFA"]))

    # 22:30-23:30 bath, bedroom
    emit(events, day, 22, jitter(45), "MOTION_BATH")
    emit(events, day, 23, jitter(0), "MOTION_BEDROOM")
    emit(events, day, 23, jitter(15), "PRESSURE_BED")

    # rare nighttime bathroom visit
    if RNG.random() < 0.25:
        emit(events, day, RNG.choice([2, 3]), jitter(30), "MOTION_BATH")


def anomaly_prolonged_inactivity(events, day: datetime):
    """Morning OK, then no activity 10:00-17:00 (resident fell or unwell)."""
    emit(events, day, 6, jitter(45), "PRESSURE_BED")
    emit(events, day, 7, jitter(0), "MOTION_BEDROOM")
    for _ in range(4):
        emit(events, day, 7, jitter(30), "MOTION_KITCHEN")
    emit(events, day, 8, jitter(45), "MOTION_BATH")
    emit(events, day, 9, jitter(30), "MOTION_LIVING")
    # GAP 10:00-17:00 (no events)
    emit(events, day, 17, jitter(30), "MOTION_LIVING")
    emit(events, day, 18, jitter(30), "MOTION_KITCHEN")
    emit(events, day, 22, jitter(0), "MOTION_BEDROOM")
    emit(events, day, 22, jitter(15), "PRESSURE_BED")


def anomaly_nighttime_activity(events, day: datetime):
    """Normal day plus heavy 01:00-04:00 motion (possible disorientation)."""
    normal_day(events, day)
    for _ in range(15):
        h = RNG.choice([1, 2, 3])
        emit(events, day, h, jitter(30, 25), RNG.choice(["MOTION_HALL", "MOTION_KITCHEN", "MOTION_LIVING"]))
    emit(events, day, 2, jitter(0), "DOOR_FRIDGE")
    emit(events, day, 3, jitter(30), "DOOR_ENTRANCE")


def anomaly_missed_routine(events, day: datetime):
    """No kitchen activity in the morning 07:00-08:00 (missed breakfast)."""
    emit(events, day, 6, jitter(45), "PRESSURE_BED")
    emit(events, day, 7, jitter(0), "MOTION_BEDROOM")
    # NO kitchen 07-08
    emit(events, day, 9, jitter(30), "MOTION_BATH")
    # rest of day is normal-ish
    for _ in range(RNG.randint(5, 9)):
        h = RNG.choice([10, 11, 14, 15, 16])
        emit(events, day, h, jitter(30, 25), RNG.choice(["MOTION_LIVING", "PRESSURE_SOFA"]))
    emit(events, day, 12, jitter(20), "MOTION_KITCHEN")
    emit(events, day, 18, jitter(30), "MOTION_KITCHEN")
    emit(events, day, 22, jitter(45), "MOTION_BEDROOM")
    emit(events, day, 23, jitter(0), "PRESSURE_BED")


def generate(days: int = 30, start_date: str = "2026-01-01") -> pd.DataFrame:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    events = []

    for d in range(days):
        day = start + timedelta(days=d)
        # last three days are labelled anomalies
        if d == days - 3:
            anomaly_prolonged_inactivity(events, day)
        elif d == days - 2:
            anomaly_nighttime_activity(events, day)
        elif d == days - 1:
            anomaly_missed_routine(events, day)
        else:
            normal_day(events, day)

    df = pd.DataFrame(events, columns=["timestamp", "sensor_id", "event"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "data", "sensor_events.csv")
    df = generate()
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} events to {out}")
    print(df.head())
