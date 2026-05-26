"""
anomaly_model.py
----------------
Time-series anomaly detection for smart-home sensor data.

Two detectors are provided so the evaluation can show that the main model
EARNS its place against a trivial baseline (this is the project's
"compare against a documented default" requirement):

  1. ThresholdBaseline  -- the "dumb" model. Flags a day if total daily
     sensor activity falls outside a fixed mean +/- k*std band learned
     from training days. No notion of *when* activity happens.

  2. RoutineModel       -- the main model. Splits each day into time-of-day
     blocks (night / morning / day / evening), learns a per-block activity
     profile from normal training days, and scores a test day by how far
     each block deviates (robust z-score). This captures *night movement*
     and *missed morning routine*, which the baseline structurally cannot.

CALEGIVER NOTIFICATION / SAFETY ESCALATION POLICY
  Detection != alarm. We map a numeric anomaly score to one of three
  escalation tiers, deliberately conservative to limit false alarms:

     LOG      -- record only, no notification (mild deviation).
     NOTIFY   -- soft caregiver notification ("check in when convenient").
     URGENT   -- prompt caregiver attention requested.

  The system NEVER contacts emergency services autonomously. It is a
  prototype, not a clinically validated medical device -- this limitation
  is stated in the evaluation report and the paper.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

SENSOR_COLS = ["motion_living", "motion_bedroom", "motion_kitchen",
               "motion_bathroom", "door_front", "fridge_open"]

# Time-of-day blocks, in minutes from midnight.
BLOCKS = {
    "night":   (0, 390),       # 00:00-06:30
    "morning": (390, 510),     # 06:30-08:30
    "day":     (510, 1080),    # 08:30-18:00
    "evening": (1080, 1440),   # 18:00-24:00
}

ESCALATION_TIERS = ("LOG", "NOTIFY", "URGENT")


def _day_matrix(day_df: pd.DataFrame) -> pd.DataFrame:
    """Strip metadata columns, keep only sensor signal for one day."""
    return day_df[SENSOR_COLS]


# --------------------------------------------------------------------------
# Baseline detector
# --------------------------------------------------------------------------
class ThresholdBaseline:
    """Documented-default baseline: total-activity band."""

    def __init__(self, k: float = 2.5):
        self.k = k
        self.mean_ = None
        self.std_ = None

    def fit(self, train_days: list[pd.DataFrame]) -> "ThresholdBaseline":
        totals = [int(_day_matrix(d).values.sum()) for d in train_days]
        self.mean_ = float(np.mean(totals))
        self.std_ = float(np.std(totals) + 1e-9)
        return self

    def score(self, day_df: pd.DataFrame) -> float:
        total = int(_day_matrix(day_df).values.sum())
        return abs(total - self.mean_) / self.std_


# --------------------------------------------------------------------------
# Main detector
# --------------------------------------------------------------------------
class RoutineModel:
    """Per-time-block routine profile with robust deviation scoring."""

    def __init__(self):
        self.block_mean_: dict[str, float] = {}
        self.block_mad_: dict[str, float] = {}

    @staticmethod
    def _block_activity(day_df: pd.DataFrame) -> dict[str, float]:
        m = _day_matrix(day_df)
        out = {}
        for name, (a, b) in BLOCKS.items():
            # iloc by minute position; index is datetime so use positional
            out[name] = float(m.iloc[a:b].values.sum())
        return out

    def fit(self, train_days: list[pd.DataFrame]) -> "RoutineModel":
        per_block: dict[str, list[float]] = {k: [] for k in BLOCKS}
        for d in train_days:
            for name, val in self._block_activity(d).items():
                per_block[name].append(val)
        for name, vals in per_block.items():
            arr = np.asarray(vals, dtype=float)
            med = float(np.median(arr))
            # Median absolute deviation -> robust to the odd weird train day
            mad = float(np.median(np.abs(arr - med))) * 1.4826
            self.block_mean_[name] = med
            self.block_mad_[name] = mad + 1e-6
        return self

    def score_blocks(self, day_df: pd.DataFrame) -> dict[str, float]:
        """Per-block robust z-score (absolute)."""
        act = self._block_activity(day_df)
        return {name: abs(act[name] - self.block_mean_[name])
                / self.block_mad_[name] for name in BLOCKS}

    def score(self, day_df: pd.DataFrame) -> float:
        """Overall day score = worst (max) block deviation."""
        return max(self.score_blocks(day_df).values())

    def explain(self, day_df: pd.DataFrame) -> str:
        """Human-readable reason for the dashboard / caregiver message.

        NOTE: this returns free text and is for HOME-SIDE logging/debugging
        only. To send anything to the caregiver side, use explain_minimal()
        and pass its fields through privacy.minimize()."""
        blocks = self.score_blocks(day_df)
        worst = max(blocks, key=blocks.get)
        act = self._block_activity(day_df)
        direction = ("less" if act[worst] < self.block_mean_[worst]
                     else "more")
        readable = {"night": "overnight", "morning": "the morning routine",
                    "day": "daytime", "evening": "the evening"}[worst]
        return (f"{direction}-than-usual activity during {readable} "
                f"(deviation score {blocks[worst]:.1f})")

    def explain_minimal(self, day_df: pd.DataFrame) -> dict:
        """Privacy-minimal explanation: ONLY the coarse fields permitted to
        cross the home/caregiver boundary. No raw counts, no per-minute
        data, no fine timestamps -- just block, direction and worst score.
        These map directly onto privacy.minimize()."""
        blocks = self.score_blocks(day_df)
        worst = max(blocks, key=blocks.get)
        act = self._block_activity(day_df)
        direction = ("less" if act[worst] < self.block_mean_[worst]
                     else "more")
        return {"block": worst, "direction": direction,
                "score": float(blocks[worst])}


# --------------------------------------------------------------------------
# Escalation logic
# --------------------------------------------------------------------------
def escalate(score: float,
             notify_at: float = 3.0,
             urgent_at: float = 6.0) -> str:
    """Map a numeric anomaly score to a caregiver escalation tier."""
    if score >= urgent_at:
        return "URGENT"
    if score >= notify_at:
        return "NOTIFY"
    return "LOG"


def caregiver_message(tier: str, date_str: str, reason: str) -> str | None:
    """Build the notification text. Returns None for LOG tier (no message)."""
    if tier == "LOG":
        return None
    if tier == "NOTIFY":
        return (f"[Check-in suggested] On {date_str}, the home routine "
                f"showed {reason}. Consider checking in when convenient. "
                f"This is an automated prototype alert, not a medical "
                f"assessment.")
    return (f"[Attention requested] On {date_str}, the home routine showed "
            f"{reason}. Please check in with the resident. This is an "
            f"automated prototype alert and does not contact emergency "
            f"services.")
