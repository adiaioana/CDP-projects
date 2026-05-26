"""
privacy.py
----------
Privacy-by-design enforcement layer.

The earlier version *claimed* data minimization in docstrings. This module
makes it a code boundary. The core idea is a HOME / CAREGIVER split:

    [ HOME SIDE ]                         [ CAREGIVER SIDE ]
    raw per-minute sensor data            never sees raw data
    detector runs here                    sees only a CaregiverVerdict
            |                                     ^
            +------ minimize() ------- gate -------+
                    (drops raw signal)   (consent + access control)

Nothing in this module is decorative. Each class removes a concrete
capability from a downstream component:

  * MinimalVerdict   -- the ONLY object allowed to cross to the caregiver
                        side. Carries a tier, a coarse block name and a
                        rounded score. No per-minute states, no room-level
                        counts, no timestamps finer than a date.
  * ConsentGate      -- the monitored resident can pause monitoring. While
                        paused, no verdict is produced or delivered.
  * RetentionPolicy  -- raw sensor data has a maximum age; expired data is
                        purged. Implements the "data minimization" and
                        "no indefinite retention" requirements.
  * AuditLog         -- every caregiver access to a verdict is recorded so
                        the resident can see who saw what. Monitoring
                        without transparency is surveillance.

THREAT MODEL (summary; full version in PRIVACY_THREAT_MODEL.md)
  In scope:  local network observer, an over-curious caregiver, accidental
             over-collection, indefinite retention.
  Out of scope / honestly NOT solved:  a caregiver who is themselves the
             threat actor but still legitimately holds dashboard access; a
             global passive network adversary defeating Tor via traffic
             correlation; physical access to the in-home device.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta

# Coarse time-of-day blocks are the FINEST temporal granularity the
# caregiver side is ever allowed to see. Minute-level data stays home.
ALLOWED_BLOCKS = ("night", "morning", "day", "evening")
ALLOWED_TIERS = ("LOG", "NOTIFY", "URGENT")


# --------------------------------------------------------------------------
# 1. Minimal verdict -- the only object that crosses the boundary
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class MinimalVerdict:
    """The single data structure permitted to leave the home side.

    Deliberately cannot carry raw sensor signal. `score` is rounded to one
    decimal so it cannot be used to reconstruct exact activity counts.
    `reason` is a fixed coarse phrase, not free text derived from raw data.
    """
    date: str               # ISO date only -- no finer timestamp
    tier: str               # LOG / NOTIFY / URGENT
    block: str              # which coarse block deviated
    score: float            # rounded deviation score
    direction: str          # "more" or "less" activity than usual

    def __post_init__(self):
        if self.tier not in ALLOWED_TIERS:
            raise ValueError(f"illegal tier: {self.tier}")
        if self.block not in ALLOWED_BLOCKS:
            raise ValueError(f"illegal block: {self.block}")

    def caregiver_text(self) -> str | None:
        """Coarse, non-clinical message. LOG produces no notification."""
        if self.tier == "LOG":
            return None
        readable = {"night": "overnight", "morning": "the morning routine",
                    "day": "the daytime period",
                    "evening": "the evening"}[self.block]
        sev = ("Check-in suggested" if self.tier == "NOTIFY"
               else "Attention requested")
        return (f"[{sev}] On {self.date}, {self.direction}-than-usual "
                f"activity during {readable}. Automated prototype alert; "
                f"not a medical assessment and does not contact emergency "
                f"services.")


def minimize(date_str: str, tier: str, block: str,
             raw_score: float, direction: str) -> MinimalVerdict:
    """Construct the minimal verdict from home-side detector output.

    This is the ONLY sanctioned way to move information across the
    boundary. Raw sensor frames are arguments to the detector, never to
    this function."""
    return MinimalVerdict(
        date=date_str, tier=tier, block=block,
        score=round(float(raw_score), 1), direction=direction,
    )


# --------------------------------------------------------------------------
# 2. Consent gate -- the resident can pause monitoring
# --------------------------------------------------------------------------
class ConsentGate:
    """Resident-controlled switch. Monitoring a person is only acceptable
    if that person can stop it. While paused, the pipeline emits nothing."""

    def __init__(self, monitoring_enabled: bool = True):
        self._enabled = monitoring_enabled
        self._changed_at = datetime.now()

    def pause(self) -> None:
        self._enabled = False
        self._changed_at = datetime.now()

    def resume(self) -> None:
        self._enabled = True
        self._changed_at = datetime.now()

    @property
    def active(self) -> bool:
        return self._enabled

    def status(self) -> dict:
        return {"monitoring_active": self._enabled,
                "since": self._changed_at.isoformat(timespec="seconds")}


# --------------------------------------------------------------------------
# 3. Retention policy -- raw data has a maximum lifetime
# --------------------------------------------------------------------------
class RetentionPolicy:
    """Enforces a maximum age for raw sensor data.

    Raw per-minute data is the most sensitive asset; it must not accumulate
    indefinitely. `purge_expired` drops days older than `max_age_days`."""

    def __init__(self, max_age_days: int = 7):
        self.max_age_days = max_age_days

    def cutoff(self, today: date | None = None) -> date:
        today = today or date.today()
        return today - timedelta(days=self.max_age_days)

    def purge_expired(self, raw_by_date: dict[str, object],
                      today: date | None = None) -> dict:
        """Return (kept_dict, purge_report). raw_by_date keys are ISO dates."""
        cut = self.cutoff(today)
        kept, purged = {}, []
        for k, v in raw_by_date.items():
            if date.fromisoformat(k) >= cut:
                kept[k] = v
            else:
                purged.append(k)
        return kept, {"max_age_days": self.max_age_days,
                      "cutoff": cut.isoformat(),
                      "purged_dates": purged,
                      "purged_count": len(purged)}


# --------------------------------------------------------------------------
# 4. Audit log -- caregiver access is transparent to the resident
# --------------------------------------------------------------------------
class AuditLog:
    """Records every caregiver access to a verdict. The resident is
    entitled to read this log: asymmetric monitoring without transparency
    is surveillance, which the project brief forbids."""

    def __init__(self):
        self._entries: list[dict] = []

    def record_access(self, viewer: str, verdict: MinimalVerdict) -> None:
        self._entries.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "viewer": viewer,
            "verdict_date": verdict.date,
            "verdict_tier": verdict.tier,
        })

    def for_resident(self) -> list[dict]:
        """The view the monitored person sees: who accessed what, when."""
        return list(self._entries)

    def summary(self) -> dict:
        viewers = sorted({e["viewer"] for e in self._entries})
        return {"total_accesses": len(self._entries), "viewers": viewers}


# --------------------------------------------------------------------------
# Pipeline glue: produce a verdict only if consent allows, log on delivery
# --------------------------------------------------------------------------
class PrivacyAwarePipeline:
    """Ties the four mechanisms together. The caregiver side interacts
    ONLY through this object and therefore can never reach raw data."""

    def __init__(self, consent: ConsentGate, audit: AuditLog):
        self.consent = consent
        self.audit = audit
        self._verdicts: list[MinimalVerdict] = []

    def submit(self, verdict: MinimalVerdict) -> bool:
        """Home side submits a minimal verdict. Dropped if consent paused."""
        if not self.consent.active:
            return False
        self._verdicts.append(verdict)
        return True

    def caregiver_feed(self, viewer: str) -> list[dict]:
        """Caregiver reads alerts. Every read is audited."""
        if not self.consent.active:
            return []
        feed = []
        for v in self._verdicts:
            self.audit.record_access(viewer, v)
            text = v.caregiver_text()
            if text:
                feed.append({"date": v.date, "tier": v.tier, "text": text})
        return feed


if __name__ == "__main__":
    # Smoke test of the boundary.
    consent = ConsentGate(True)
    audit = AuditLog()
    pipe = PrivacyAwarePipeline(consent, audit)

    v = minimize("2025-01-08", "URGENT", "day", 7.42, "less")
    pipe.submit(v)
    print("feed:", json.dumps(pipe.caregiver_feed("caregiver_A"), indent=2))

    consent.pause()
    print("paused -> feed:", pipe.caregiver_feed("caregiver_A"))
    print("audit:", json.dumps(audit.summary(), indent=2))
