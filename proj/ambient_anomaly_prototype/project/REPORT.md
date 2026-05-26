# Evaluation Report — Ambient Anomaly Detection Prototype

**Scope.** Small reproducible evaluation of the prototype against a simulated
30-day single-resident dataset (1,570 sensor events, 9 anonymized sensors).
The final three days of the dataset each contain one injected anomaly.

## 1. Dataset

| Item | Value |
|------|-------|
| Days simulated | 30 |
| Total events | 1,570 |
| Sensors | 9 (motion, door, pressure) |
| Aggregation window | 1 hour |
| Labelled anomaly days | 3 (Jan 28–30) |

The dataset and labels are produced deterministically by
`scripts/simulate_data.py` (`random.Random(42)`).

## 2. Scenarios

| # | Scenario | Day | Description |
|---|----------|-----|-------------|
| 1 | Normal | Jan 1–27 | Routine days with morning kitchen, day-time living, evening dinner, night sleep, occasional brief bathroom visits. |
| 2 | Anomaly: prolonged inactivity | Jan 28 | No sensor activity 10:00–17:00 (7 hours). |
| 3 | Anomaly: unusual nighttime activity | Jan 29 | 17 events between 01:00–04:00 in addition to a normal day. |
| 4 | Anomaly: missed routine | Jan 30 | No kitchen events 07:00–09:00 (normally ≥3 every day). |
| 5 | Failure case: sensor outage | Jan 15 | All events for the day removed at the data layer. |

## 3. Results

### Rule-based detection

| Scenario | Detected | First alert | Latency from onset |
|----------|----------|-------------|--------------------|
| Prolonged inactivity (Jan 28) | ✓ | 15:00 | 5.0 h |
| Unusual nighttime activity (Jan 29) | ✓ | 02:00 | 1.0 h |
| Missed morning routine (Jan 30) | ✓ | 08:00 | 1.0 h |

Rule-layer **false positives on labelled-normal days: 0**.

### Unsupervised model (IsolationForest, per hour-of-day, contamination=0.05)

| Metric | Value |
|--------|-------|
| Normal hours observed | 645 |
| Model-layer alerts on normal hours | 9 |
| False-positive rate | 1.40 % |

The model layer adds context (e.g. flagged unusually quiet evening hours
during the inactivity scenario) but on its own is too noisy to drive
caregiver notifications. It is included as a complementary "look-here"
signal, not a primary alarm.

### Detection runtime

End-to-end (load → features → rules + model → cooldown) on 30 days of data
runs in **~2.6 s on a single CPU core**, well within "local prototype" budget.

## 4. False-positive analysis

The rule layer produced zero false positives on this dataset. The model
layer produced 9. Inspecting them:

- **Quiet evenings (3 cases).** Hours where the resident went out earlier
  than usual and skipped the typical evening living-room window. These are
  legitimate behavioural variations, not problems.
- **Late-night bathroom visits (3 cases).** Occasional 02:00–03:00 single
  events flagged because most nights have zero activity in that hour.
- **Shortened lunch (3 cases).** Days with fewer-than-usual midday kitchen
  events.

These match the categories the spec calls out as likely false-positive
sources: irregular schedules, visitors, sensor noise. A 30-day baseline is
short; with longer history the model would learn that occasional quiet
evenings are themselves normal. A simple mitigation is to require a model
alert to repeat over an extended window before surfacing it to a caregiver.

## 5. Failure case: sensor outage

Removing all Jan 15 events at the data layer causes the detector to raise
a **false prolonged-inactivity alert** for that day.

This is the expected behaviour — the detector cannot distinguish a quiet
resident from a dead sensor without out-of-band information. **Mitigation:**
a sensor-health watchdog (e.g. heartbeat checks, expected daily event
count per sensor) should run alongside the anomaly detector and suppress
or relabel inactivity alerts when sensor reliability is in doubt. This is
out of scope for the prototype but is the natural next step.

## 6. Privacy & data minimization

The prototype is designed around the principle that *the least invasive
data that answers the question is the right data*.

**What is collected.** Timestamped events from binary ambient sensors
(motion, door open/close, pressure pad). Every event has three fields:
timestamp, anonymized sensor ID, state.

**What is not collected.** No audio, no video, no images, no identity
information, no biometric data, no location data outside the home.

**Why it is sufficient.** Routine deviations of the kind specified
(prolonged inactivity, abnormal night activity, missed routines) are
visible in aggregate event counts. Identifying *who* is in the home or
*what* they are doing in detail is not required.

**Minimization mechanisms.**

- IDs are static room/device tags (`MOTION_KITCHEN`), not per-person.
- Modelling operates on 1-hour aggregates, not raw sequences, limiting
  behavioural reconstruction.
- All processing runs locally; no network egress is part of the prototype.
- The model output is a small set of alerts (timestamp, type, severity,
  short text), not raw event traces.

**What we do not do.**

- No identity inference.
- No cross-resident comparison.
- No attempt to deanonymize.
- No medical diagnosis. The prototype produces *deviation* alerts only;
  interpretation is for a human carer.

**Risks that remain.** Even anonymized event streams could in principle
identify a household given enough auxiliary information (e.g. a known
schedule). Anyone deploying a system like this should treat raw event
logs as sensitive, store them only as long as needed, and restrict access.

## 7. Honest limitations

- **Simulated data.** The behavioural model is hand-coded, not learned
  from real residents. Real homes have more visitors, more irregular
  sleep, multi-resident interaction, pet activity, and seasonal drift.
- **Short baseline.** 30 days is short; weekly and seasonal patterns are
  not captured.
- **Single resident.** Multi-resident homes need disambiguation that the
  current sensor set cannot do.
- **Threshold sensitivity.** The 6-hour inactivity threshold and 2×
  nighttime ratio are reasonable defaults but should be personalised in
  any real deployment.
- **No sensor-health layer.** As shown by the failure case, the detector
  trusts its inputs. Production use needs an outage detector alongside it.
