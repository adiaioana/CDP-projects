# Hearth — Smart-Home Wellbeing Monitor (course prototype)

Detects routine deviations (inactivity, unusual nighttime movement, missed
routines) in a single-occupant household from ambient sensor data, streams
events to a caregiver dashboard over a configurable transport
(direct / VPN / Tor), and enforces **privacy by design** through a
home/caregiver boundary.

## Quick start

```bash
pip install numpy pandas scikit-learn scipy PySocks --break-system-packages
python3 src/data_generator.py     # writes data/sensor_dataset.csv
python3 src/evaluate.py           # writes results/evaluation.json + prints report
python3 -m http.server 8000       # then open http://localhost:8000/dashboard/
```

## Privacy architecture: the home / caregiver boundary

The central design choice. Privacy is enforced by code structure, not by
docstrings:

```
[ HOME SIDE ]                          [ CAREGIVER SIDE ]
raw per-minute sensor data             never sees raw data
detector runs here                    sees only MinimalVerdict objects
        |                                      ^
        +----- explain_minimal() ----- gate ---+
               minimize()       consent + audit
```

Four enforced mechanisms (`src/privacy.py`):

- **MinimalVerdict** — the only object allowed across the boundary. 5 coarse
  fields; cannot carry per-minute states or room counts.
- **ConsentGate** — the monitored resident can pause monitoring; paused ⇒ no
  verdict accepted or delivered, even URGENT.
- **RetentionPolicy** — raw sensor data older than the window is purged.
- **AuditLog** — every caregiver access is recorded and readable by the
  resident.

Measured in `evaluate.py` Part C: data reduction at the boundary (1728×),
the consent-pause negative case, and the retention purge.

## Files → deliverables

| File | Deliverable it serves |
|---|---|
| `src/data_generator.py` | **Dataset protocol** — synthetic ambient data, anomaly injection |
| `src/anomaly_model.py` | **Prototype** — RoutineModel + baseline, escalation logic |
| `src/privacy.py` | **Privacy-by-design** — boundary, consent, retention, audit |
| `src/transport.py` | Transport comparison (direct/VPN/Tor), threat-model notes |
| `src/evaluate.py` | **Evaluation report** data — Parts A (detection), B (transport), C (privacy) |
| `dashboard/index.html` | **Dashboard** — caregiver feed, daily review, transport + privacy panels |
| `PRIVACY_THREAT_MODEL.md` | **Ethical review** — threat model, ethics checklist, residual risk |

## Negative / failure cases (required, not hidden)

1. **Benign-atypical day** — a guest/sick day both models false-positive on.
2. **Tor transport failure** — logged gracefully when no Tor daemon runs.
3. **Consent-pause delivery case** — an URGENT verdict deliberately dropped
   while the resident has paused monitoring.

## Known limitations (state these; do not overclaim)

- Single synthetic occupant; not clinically validated; short evaluation window.
- The model cannot yet separate "abnormal but safe" from "abnormal and
  dangerous" — see the false-positive analysis.
- Privacy is reduced, not absolute: a trusted-but-malicious caregiver,
  traffic correlation against Tor, and physical device access remain — see
  `PRIVACY_THREAT_MODEL.md` section 5.
