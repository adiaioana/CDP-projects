"""
evaluate.py
-----------
End-to-end evaluation harness. Produces every number the IEEE-style paper
and evaluation report need.

  PART A -- Anomaly detection
     RoutineModel vs ThresholdBaseline on the same held-out days. Detection
     output is routed through the PRIVACY BOUNDARY (privacy.py): the
     caregiver feed is built only from MinimalVerdict objects, never from
     raw sensor frames. Includes the false-positive analysis on the
     benign-atypical day (the required negative case).

  PART B -- Transport comparison
     Same live event stream over direct / vpn / tor. The Tor path doubles
     as the transport failure experiment when no Tor daemon is present.

  PART C -- Privacy mechanism experiments
     Demonstrates the privacy controls as real, testable behaviour:
       C1. Data minimization -- measures how many fields the caregiver
           side receives vs how many the home side holds.
       C2. Consent gate -- shows the feed goes empty when the resident
           pauses monitoring (a deliberate negative case for delivery).
       C3. Retention purge -- shows raw data older than the policy window
           is dropped.

Everything is seeded and reproducible. Results -> results/evaluation.json.
"""

from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_generator import generate_dataset                          # noqa: E402
from anomaly_model import (RoutineModel, ThresholdBaseline,           # noqa: E402
                           escalate)
from transport import run_transport_benchmark                        # noqa: E402
from privacy import (ConsentGate, AuditLog, RetentionPolicy,          # noqa: E402
                     PrivacyAwarePipeline, minimize)

RESULTS = Path(__file__).resolve().parent


def _split_days(ds: pd.DataFrame):
    for day, grp in ds.groupby("day"):
        yield int(day), grp, grp["label"].iloc[0]


# --------------------------------------------------------------------------
# PART A -- detection, routed through the privacy boundary
# --------------------------------------------------------------------------
def part_a_detection() -> dict:
    train_ds = generate_dataset(14, anomaly_schedule={}, seed=1)
    test_schedule = {1: "inactivity", 3: "night_movement",
                     5: "missed_routine", 7: "benign_atypical",
                     9: "mild_inactivity"}
    test_ds = generate_dataset(12, anomaly_schedule=test_schedule, seed=2)
    train_days = [g for _, g, _ in _split_days(train_ds)]

    routine = RoutineModel().fit(train_days)
    baseline = ThresholdBaseline(k=2.5).fit(train_days)

    # The home side runs the detector and submits ONLY minimal verdicts.
    consent = ConsentGate(monitoring_enabled=True)
    audit = AuditLog()
    pipeline = PrivacyAwarePipeline(consent, audit)

    rows = []
    for day, df, label in _split_days(test_ds):
        is_true_event = label in ("inactivity", "night_movement",
                                  "missed_routine", "mild_inactivity")
        r_score = routine.score(df)
        b_score = baseline.score(df)
        r_tier = escalate(r_score)

        # ---- privacy boundary crossing ----
        m = routine.explain_minimal(df)            # coarse fields only
        date_str = f"2025-02-{day + 1:02d}"
        verdict = minimize(date_str, r_tier, m["block"],
                           m["score"], m["direction"])
        pipeline.submit(verdict)                   # raw df never crosses

        rows.append({
            "day": day, "label": label, "true_event": is_true_event,
            "routine_score": round(r_score, 2), "routine_tier": r_tier,
            "baseline_score": round(b_score, 2),
            "baseline_tier": escalate(b_score),
            # only the minimal, boundary-crossing fields are kept here:
            "verdict_block": verdict.block,
            "verdict_direction": verdict.direction,
        })
    res = pd.DataFrame(rows)

    def _metrics(tier_col):
        alarmed = res[tier_col].isin(["NOTIFY", "URGENT"])
        tp = int((alarmed & res["true_event"]).sum())
        fn = int((~alarmed & res["true_event"]).sum())
        fp = int((alarmed & ~res["true_event"]).sum())
        tn = int((~alarmed & ~res["true_event"]).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        return {"tp": tp, "fn": fn, "fp": fp, "tn": tn,
                "precision": round(prec, 3), "recall": round(rec, 3)}

    benign = res[res["label"] == "benign_atypical"].iloc[0]
    fp_analysis = {
        "benign_day_index": int(benign["day"]),
        "routine_tier_on_benign": benign["routine_tier"],
        "baseline_tier_on_benign": benign["baseline_tier"],
        "interpretation": (
            "The benign-atypical day (guest/sick day) is unusual but NOT a "
            "safety event. Any NOTIFY/URGENT here is a false positive. This "
            "is the project's required negative case."),
    }

    # The caregiver feed is built ONLY from the pipeline -- it has no path
    # back to raw sensor data by construction.
    feed = pipeline.caregiver_feed(viewer="caregiver_A")

    return {
        "per_day": rows,
        "routine_model": _metrics("routine_tier"),
        "baseline_model": _metrics("baseline_tier"),
        "false_positive_analysis": fp_analysis,
        "caregiver_feed": feed,
        "audit_summary": audit.summary(),
        "audit_entries": audit.for_resident(),
    }


# --------------------------------------------------------------------------
# PART B -- transport
# --------------------------------------------------------------------------
def part_b_transport() -> dict:
    events = [{"sensor": "motion_kitchen", "value": 1, "seq": i}
              for i in range(300)]
    return {t: run_transport_benchmark(events, transport=t)
            for t in ("direct", "vpn", "tor")}


# --------------------------------------------------------------------------
# PART C -- privacy mechanism experiments
# --------------------------------------------------------------------------
def part_c_privacy() -> dict:
    # C1. Data minimization: count fields held home-side vs sent caregiver-side.
    home_side_fields = 6 * 1440          # raw sensor matrix for one day
    verdict = minimize("2025-02-08", "URGENT", "day", 7.4, "less")
    caregiver_side_fields = len(verdict.__dataclass_fields__)
    minimization = {
        "home_side_raw_values_per_day": home_side_fields,
        "caregiver_side_fields_per_verdict": caregiver_side_fields,
        "reduction_ratio": round(home_side_fields / caregiver_side_fields, 1),
        "note": ("The caregiver side cannot reconstruct per-minute activity "
                 "or room-level counts: those values never cross the "
                 "boundary. Minimization is enforced by the MinimalVerdict "
                 "schema, not by convention."),
    }

    # C2. Consent gate: a NEGATIVE delivery case -- resident pauses monitoring.
    consent = ConsentGate(True)
    audit = AuditLog()
    pipe = PrivacyAwarePipeline(consent, audit)
    pipe.submit(minimize("2025-02-09", "NOTIFY", "night", 3.4, "more"))
    feed_active = pipe.caregiver_feed("caregiver_A")
    consent.pause()
    submitted_while_paused = pipe.submit(
        minimize("2025-02-10", "URGENT", "day", 8.0, "less"))
    feed_paused = pipe.caregiver_feed("caregiver_A")
    consent_experiment = {
        "feed_size_when_active": len(feed_active),
        "submit_accepted_while_paused": submitted_while_paused,
        "feed_size_when_paused": len(feed_paused),
        "interpretation": ("While the resident has paused monitoring, no "
                           "verdict is accepted and the caregiver feed is "
                           "empty. This is a deliberate negative case: the "
                           "resident's consent overrides alert delivery, "
                           "even for an URGENT-tier event."),
    }

    # C3. Retention purge: raw data older than the window is dropped.
    policy = RetentionPolicy(max_age_days=7)
    raw_by_date = {f"2025-02-{d:02d}": f"<raw day {d}>" for d in range(1, 16)}
    kept, report = policy.purge_expired(raw_by_date,
                                        today=date(2025, 2, 15))
    retention_experiment = {
        "days_before_purge": len(raw_by_date),
        "days_after_purge": len(kept),
        "purge_report": report,
        "interpretation": ("Raw per-minute sensor data is the most "
                           "sensitive asset and is not retained "
                           "indefinitely; days older than the policy "
                           "window are purged."),
    }

    return {
        "data_minimization": minimization,
        "consent_gate_experiment": consent_experiment,
        "retention_experiment": retention_experiment,
    }


# --------------------------------------------------------------------------
def _print_report(report: dict) -> None:
    a = report["detection"]
    print("\n" + "=" * 66)
    print("PART A  --  ANOMALY DETECTION  (via privacy boundary)")
    print("=" * 66)
    for r in a["per_day"]:
        print(f"day {r['day']:>2} {r['label']:<16} "
              f"true={str(r['true_event']):<5} "
              f"routine={r['routine_score']!s:>6} {r['routine_tier']:<8} "
              f"baseline={r['baseline_score']!s:>6} {r['baseline_tier']}")
    rm, bm = a["routine_model"], a["baseline_model"]
    print("-" * 66)
    print(f"RoutineModel : precision={rm['precision']} recall={rm['recall']}")
    print(f"Baseline     : precision={bm['precision']} recall={bm['recall']}")
    fp = a["false_positive_analysis"]
    print(f"False-positive spotlight (benign day {fp['benign_day_index']}): "
          f"routine={fp['routine_tier_on_benign']} "
          f"baseline={fp['baseline_tier_on_benign']}")
    print(f"Caregiver feed: {len(a['caregiver_feed'])} alert(s); "
          f"audit recorded {a['audit_summary']['total_accesses']} access(es)")

    print("\n" + "=" * 66)
    print("PART B  --  TRANSPORT COMPARISON")
    print("=" * 66)
    for t, m in report["transport"].items():
        ok = "OK" if m["connection_success"] else "FAIL"
        line = f"[{t.upper():<6}] {ok:<5}"
        if m["connection_success"]:
            line += (f" latency {m['latency_ms_mean']} ms  "
                     f"throughput {m['throughput_eps']} ev/s")
        else:
            line += f" {m['error']}  (documented failure case)"
        print(line)

    print("\n" + "=" * 66)
    print("PART C  --  PRIVACY MECHANISM EXPERIMENTS")
    print("=" * 66)
    c = report["privacy"]
    dm = c["data_minimization"]
    print(f"C1 data minimization : home holds "
          f"{dm['home_side_raw_values_per_day']} raw values/day; "
          f"caregiver receives {dm['caregiver_side_fields_per_verdict']} "
          f"fields/verdict  (reduction {dm['reduction_ratio']}x)")
    ce = c["consent_gate_experiment"]
    print(f"C2 consent gate      : feed active={ce['feed_size_when_active']}, "
          f"submit-while-paused accepted={ce['submit_accepted_while_paused']}, "
          f"feed paused={ce['feed_size_when_paused']}")
    re = c["retention_experiment"]
    print(f"C3 retention purge   : "
          f"{re['days_before_purge']} days -> {re['days_after_purge']} "
          f"days kept ({re['purge_report']['purged_count']} purged, "
          f"cutoff {re['purge_report']['cutoff']})")


def main() -> None:
    np.random.seed(0)
    report = {
        "detection": part_a_detection(),
        "transport": part_b_transport(),
        "privacy": part_c_privacy(),
    }
    out_path = RESULTS / "evaluation.json"
    out_path.write_text(json.dumps(report, indent=2))
    _print_report(report)
    print(f"\nFull machine-readable results -> {out_path}")


if __name__ == "__main__":
    main()
