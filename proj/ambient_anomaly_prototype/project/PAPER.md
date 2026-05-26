# A Lightweight, Privacy-Preserving Anomaly Detector for Ambient Smart-Home Sensor Streams

*Anonymous Authors*  
*[Affiliation]*

## Abstract

We present a compact research prototype for routine-anomaly detection in
ambient smart-home sensor streams. The system targets three socially
relevant scenarios — prolonged inactivity, unusual nighttime movement, and
missed daily routines — using only binary motion, door, and pressure
sensors. We combine three explainable rule-based detectors with a per-hour
IsolationForest model trained on 1-hour aggregate features. On a 30-day
simulated single-resident dataset, the rule layer detects all three
labelled anomalies with zero false positives, and the model layer
contributes a 1.4 % false-positive rate over 645 normal hours. End-to-end
detection runs in roughly 2.6 s. The design is deliberately minimal:
~600 lines of Python, no cloud, no audio or video, all processing local.
We discuss limitations including sensor outages, short baselines, and
threshold sensitivity, and we describe the privacy-by-design choices that
make the system suitable as a teaching and prototyping artifact rather
than a production health-monitoring system.

**Keywords —** smart home, anomaly detection, ambient sensing,
IsolationForest, privacy by design.

## I. Introduction

Ambient sensors in the home — passive infrared motion detectors, magnetic
door contacts, pressure pads on beds and sofas — can produce a useful
behavioural signal at very low privacy cost compared to cameras or
microphones. A growing body of work uses such sensors to detect routine
deviations that may indicate health or safety problems in older adults
living alone [1], [2].

Many published systems are heavy: deep models, multi-tier streaming
infrastructures, or full cloud deployments. For research prototypes and
classroom use these are overkill, and they pull the focus away from the
small set of design choices that actually determine whether the system is
useful and respectful. This paper describes a deliberately minimal
prototype: a single Python process, two layers of detection (one
rule-based and explainable, one unsupervised and complementary), and a
simple Streamlit dashboard.

Our contributions are:

1. A small, reproducible pipeline (data → features → detection → display)
   that runs end-to-end in seconds on a laptop.
2. A combination of three explainable rule-based detectors covering the
   spec-required anomaly scenarios, complemented by a per-hour
   IsolationForest model.
3. A short, practical privacy-by-design discussion and a failure-case
   analysis (sensor outage) that highlights what such a system can and
   cannot do on its own.

## II. Related Work

The CASAS group provides public smart-home datasets and a long line of
work on activity recognition and resident monitoring [1]. Cook et al.
have studied behavioural drift as an indicator of cognitive change [2].
Anomaly detection in ambient streams has used Hidden Markov Models,
LSTMs, and more recently transformer-based approaches [3]. We do not
attempt to compete with these on accuracy; we instead argue that for many
practical deployments, a transparent rule layer plus a single
IsolationForest gives most of the value with a fraction of the
complexity. Isolation Forest [4] is a well-established baseline that is
fast, requires little tuning, and is easy to explain.

## III. Data and Features

### A. Data model

The system consumes a stream of events with the schema
`(timestamp, sensor_id, event)`. The prototype works with either real
CASAS data (after a thin adapter) or a built-in simulator. We use the
simulator throughout this paper.

The simulator models a single resident's daily routine using nine
sensors: five PIR motion sensors (bedroom, kitchen, bathroom, living
room, hallway), two door contacts (fridge, entrance), and two pressure
pads (bed, sofa). Over 30 days it produces 1,570 events. The final three
days each contain one injected anomaly:

- *Day 28:* no events from 10:00 to 17:00 (prolonged inactivity).
- *Day 29:* normal day plus 17 motion/door events between 01:00 and 04:00.
- *Day 30:* no kitchen events between 07:00 and 09:00 (missed routine).

### B. Features

Events are aggregated into one-hour windows. For each window we compute
event count, unique-sensor count, room-specific event counts (kitchen,
bedroom, bath, living, hall, door), maximum inter-event gap, hour of day,
night flag (00:00–06:00), and a rolling count of consecutive
zero-activity hours. These features are explicitly chosen to be short
(≤12 dimensions), interpretable, and resilient to sensor noise.

## IV. Detection

The system uses two complementary detection layers.

### A. Rule-based layer

Three rules implement the required scenarios:

- **Prolonged inactivity.** Trigger when the rolling zero-activity counter
  reaches 6 hours during the 08:00–20:00 window. A 4-hour cooldown
  prevents repeated alerts within the same streak.
- **Unusual nighttime activity.** Compute per-resident baseline event
  count for the 01:00–04:00 window. Trigger when a night's total is
  ≥ 2× the personal baseline. This adapts to residents who have routine
  nighttime bathroom trips.
- **Missed morning routine.** If at least five days in the observed
  history show kitchen events in the 07:00–08:59 window, then a day with
  zero such events is flagged.

These rules are explicit and auditable; a carer can be told exactly why
an alert fired.

### B. Unsupervised layer

We train one IsolationForest [4] per hour-of-day on the features in
Section III-B (with `hour` and `is_night` removed, since each model is
already conditioned on a single hour). Contamination is set to 0.05.
Training one model per hour-of-day avoids a class of trivial false
positives that a single global model produces — it would otherwise flag
every 07:00 in the dataset as anomalous merely because mornings are
busier than afternoons.

The two layers are merged into a single alert stream with a 4-hour
per-type cooldown.

## V. Evaluation

We evaluate on the simulator dataset. Although small, it is designed to
exercise each detector and is reproducible from a fixed random seed.

**Detection accuracy.** All three labelled anomalies are detected by the
rule layer with the correct type. There are zero false positives from
the rule layer over 645 labelled-normal hours.

**Latency.** Median time from anomaly onset to first alert is 1 hour for
the nighttime-activity and missed-routine scenarios (the next hourly
window after onset) and 5 hours for prolonged inactivity (the system
waits until the 6-hour threshold is crossed). The latter is by
construction: an alert sooner would also fire during normal sleep.

**Model false-positive rate.** The IsolationForest layer flags 9 of 645
normal hours, a 1.40 % rate consistent with the chosen contamination.
Inspection shows the false positives correspond to legitimate
behavioural variation (early evenings, shortened lunches, occasional
late-night bathroom visits). The model layer is therefore presented as
a secondary, low-confidence signal rather than as a primary alarm.

**Runtime.** End-to-end execution (load, features, rules, model,
cooldown) takes ~2.6 s on a single CPU core for 30 days of data.

**Failure case: sensor outage.** Dropping all events from a normal day
(Jan 15) at the data layer causes the system to raise a false
prolonged-inactivity alert. This is expected: the detector cannot tell a
quiet resident from a dead sensor. The natural next step is a
sensor-health watchdog (heartbeats, expected daily event counts per
sensor) that runs alongside the anomaly detector.

## VI. Discussion

**Strengths.** The pipeline is small enough to be read top-to-bottom in
an afternoon. Each alert is explainable in one short sentence. There
are no neural components, no cloud calls, no databases — installation
is `pip install` plus three scripts.

**Limitations.** The dataset is simulated; real homes will show more
variation and require longer baselines. Thresholds (6 h inactivity,
2× nighttime ratio) are reasonable defaults but should be personalised
in real deployment. The detector trusts its inputs and needs a
sensor-health layer to handle outages. Multi-resident homes are out of
scope without additional sensors (e.g. wearables) or disambiguation
logic.

## VII. Ethics and Privacy

We follow a *data minimisation* discipline. The prototype collects only
binary ambient events, anonymised by room and device. No audio, video,
or identity information is recorded. All processing is local; data does
not leave the host. Modelling operates on 1-hour aggregates rather than
raw sequences, limiting the granularity at which behaviour can be
reconstructed.

The system is positioned as a *deviation detector*, not a medical
device. It generates short, structured alerts; interpretation is for a
human carer. We do not attempt diagnosis, identity inference, or
cross-resident comparison.

Residual risks remain. Even anonymised event logs could in principle
identify a household given auxiliary information, and behavioural data
about an older adult is sensitive in itself. Any real deployment should
require informed consent, restrict access to raw logs, and provide a
clear opt-out path. We consider this an essential precondition for
building such systems, not an afterthought.

## VIII. Conclusion

We have described a minimal, privacy-preserving prototype for routine-
anomaly detection in ambient smart-home sensor data. The system reliably
detects the three target scenarios on a simulated dataset, runs locally
in seconds, and is small enough to be read and audited end-to-end. It is
not a finished product, and we have been explicit about what is missing
(sensor-health, personalisation, multi-resident support). Our aim is to
show that for many research and teaching purposes a system of this size
is enough, and that the privacy and explainability properties that
matter most can be designed in from the start rather than retrofitted.

## References

[1] D. J. Cook et al., "CASAS: A smart home in a box," *Computer*, vol.
46, no. 7, pp. 62–69, 2013.

[2] D. J. Cook, "Learning setting-generalized activity models for smart
spaces," *IEEE Intelligent Systems*, vol. 27, no. 1, pp. 32–38, 2012.

[3] V. Chandola, A. Banerjee, and V. Kumar, "Anomaly detection: A
survey," *ACM Computing Surveys*, vol. 41, no. 3, pp. 1–58, 2009.

[4] F. T. Liu, K. M. Ting, and Z.-H. Zhou, "Isolation Forest," in *Proc.
8th IEEE Int. Conf. Data Mining*, 2008, pp. 413–422.
