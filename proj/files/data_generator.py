"""
data_generator.py
-----------------
Generates simulated ambient smart-home sensor data for a single-occupant
household, plus controllable "anomaly" injections.

DATASET PROTOCOL (summary)
  - Source: fully synthetic. No real person is sensed. This satisfies the
    brief's "no surveillance of third parties" requirement.
  - Sensors modeled (binary/ambient only -- privacy-by-design: no cameras,
    no microphones, no PII):
        motion_living, motion_bedroom, motion_kitchen, motion_bathroom,
        door_front, fridge_open
  - Resolution: one row per minute (1440 rows/day).
  - Routine: a simple daily schedule (sleep, morning routine, daytime
    activity, evening) with stochastic noise so no two days are identical.
  - Anomaly types injectable per day:
        "none"            -> normal day
        "inactivity"      -> long flat period during waking hours
        "night_movement"  -> unusual sustained activity 01:00-04:00
        "missed_routine"  -> morning kitchen/bathroom routine absent
        "benign_atypical" -> guest visit / sick day: looks abnormal but is
                             NOT a real safety event. Used for the
                             false-positive / negative-case experiment.

Data minimization note: only the minimum signal needed for the task is
generated. We do NOT generate location traces, identities, or audio.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

SENSORS = [
    "motion_living", "motion_bedroom", "motion_kitchen",
    "motion_bathroom", "door_front", "fridge_open",
]

ANOMALY_TYPES = (
    "none", "inactivity", "night_movement", "missed_routine", "benign_atypical",
)


def _baseline_day(rng: np.random.Generator) -> pd.DataFrame:
    """One normal day, 1440 minutes, binary sensor activations."""
    minutes = np.arange(1440)
    df = pd.DataFrame({s: np.zeros(1440, dtype=int) for s in SENSORS},
                      index=minutes)

    col_pos = {s: i for i, s in enumerate(SENSORS)}

    def fire(sensor, start, end, prob):
        """Randomly activate `sensor` within [start,end) at given prob/min.

        Uses positional .iloc so the range is half-open [start, end),
        matching minute semantics (pandas label slices are inclusive)."""
        start = max(0, start)
        end = min(end, 1440)
        n = end - start
        if n <= 0:
            return
        df.iloc[start:end, col_pos[sensor]] = (rng.random(n) < prob).astype(int)

    # --- Night sleep 23:00-06:30: occasional bathroom trip ---
    fire("motion_bedroom", 0, 390, 0.02)          # 00:00-06:30 stirring
    if rng.random() < 0.6:                        # ~60% of nights: one trip
        t = rng.integers(60, 330)
        fire("motion_bathroom", t, t + 4, 0.8)

    # --- Morning routine 06:30-08:30 ---
    fire("motion_bedroom",  390, 420, 0.5)
    fire("motion_bathroom", 405, 440, 0.4)
    fire("motion_kitchen",  430, 510, 0.5)
    fire("fridge_open",     435, 500, 0.15)
    fire("motion_living",   460, 510, 0.4)

    # --- Daytime activity 08:30-18:00: roaming, errands ---
    fire("motion_living",   510, 1080, 0.18)
    fire("motion_kitchen",  510, 1080, 0.10)
    fire("motion_bathroom", 510, 1080, 0.05)
    if rng.random() < 0.7:                        # leaves the house
        t = rng.integers(540, 900)
        fire("door_front", t, t + 2, 0.9)
        fire("door_front", t + rng.integers(60, 180),
             t + rng.integers(60, 180) + 2, 0.9)

    # --- Evening 18:00-23:00 ---
    fire("motion_kitchen",  1080, 1170, 0.45)
    fire("fridge_open",     1085, 1160, 0.18)
    fire("motion_living",   1120, 1380, 0.35)
    fire("motion_bathroom", 1320, 1400, 0.3)
    fire("motion_bedroom",  1380, 1440, 0.4)
    return df


def _inject(df: pd.DataFrame, anomaly: str,
            rng: np.random.Generator) -> pd.DataFrame:
    """Mutate a baseline day to contain the requested anomaly.

    Uses positional .iloc; minute ranges are half-open [start, end)."""
    df = df.copy()
    cpos = {s: i for i, s in enumerate(SENSORS)}

    def cols(*names):
        return [cpos[n] for n in names]

    if anomaly == "none":
        pass
    elif anomaly == "inactivity":
        # Long flat period during waking hours (e.g. a fall): 11:00-16:00
        df.iloc[660:960, :len(SENSORS)] = 0
    elif anomaly == "night_movement":
        # Sustained restless activity 01:00-04:00
        for s in ("motion_living", "motion_kitchen", "motion_bedroom"):
            n = 300 - 60
            df.iloc[60:300, cpos[s]] = (rng.random(n) < 0.35).astype(int)
    elif anomaly == "missed_routine":
        # Morning kitchen + bathroom routine simply does not happen
        df.iloc[390:510, cols("motion_kitchen", "motion_bathroom",
                               "fridge_open")] = 0
    elif anomaly == "benign_atypical":
        # NEGATIVE CASE: a guest stays over / sick day. Activity is unusual
        # (late nights, extra movement, skipped errands) but NOT a safety
        # event. A good detector should ideally not escalate this; a naive
        # one will. This drives the false-positive analysis.
        for s in ("motion_living", "motion_kitchen"):
            n = 240 - 60
            df.iloc[60:240, cpos[s]] = (rng.random(n) < 0.3).astype(int)
        df.iloc[540:1080, :len(SENSORS)] = 0      # stayed in bed sick
    else:
        raise ValueError(f"unknown anomaly: {anomaly}")
    return df


def generate_dataset(n_normal_days: int = 20,
                     anomaly_schedule: dict[int, str] | None = None,
                     seed: int = 42) -> pd.DataFrame:
    """
    Build a multi-day dataset.

    anomaly_schedule maps day-index -> anomaly type for days that should be
    abnormal. All other days are normal. Returns a long DataFrame with a
    proper datetime index and a `label` column (the ground-truth anomaly
    type for that day).
    """
    rng = np.random.default_rng(seed)
    anomaly_schedule = anomaly_schedule or {}
    frames = []
    start = pd.Timestamp("2025-01-01 00:00")

    for day in range(n_normal_days):
        atype = anomaly_schedule.get(day, "none")
        day_df = _baseline_day(rng)
        day_df = _inject(day_df, atype, rng)
        idx = pd.date_range(start + pd.Timedelta(days=day),
                            periods=1440, freq="min")
        day_df.index = idx
        day_df["label"] = atype
        day_df["day"] = day
        frames.append(day_df)

    return pd.concat(frames)


if __name__ == "__main__":
    from pathlib import Path
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    schedule = {7: "inactivity", 11: "night_movement",
                14: "missed_routine", 17: "benign_atypical"}
    ds = generate_dataset(20, schedule)
    ds.to_csv(out_dir / "sensor_dataset.csv")
    print(f"Wrote {len(ds)} rows ({ds['day'].nunique()} days) "
          f"to {out_dir / 'sensor_dataset.csv'}")
    print("Anomaly days:", schedule)
