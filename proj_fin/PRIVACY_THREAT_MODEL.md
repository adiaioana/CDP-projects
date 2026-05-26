# Privacy Threat Model & Ethical Review — Hearth Prototype

This document accompanies the Hearth smart-home wellbeing monitor. It states
what the system protects against, what it deliberately does **not** solve,
and the ethical conditions under which it could be used. It is written for
the project's "clear threat models" and "ethical review" requirements.

## 1. What the system is

A single-occupant household is instrumented with binary ambient sensors
(motion, door, fridge). A detector running **in the home** scores each day
for routine deviations. Only a minimal verdict (date, tier, coarse block,
rounded score, direction) crosses to a **caregiver side**, which shows alerts
on a dashboard. It is a course prototype on synthetic data — not a clinically
validated medical device, and it never contacts emergency services.

## 2. Assets, ranked by sensitivity

1. **Raw per-minute sensor data** — most sensitive. Reveals when the resident
   sleeps, wakes, leaves, uses the bathroom. Behavioural and re-identifying.
2. **Derived routine profile** (`block_mean_`, `block_mad_`) — aggregated, but
   still describes habitual behaviour.
3. **Minimal verdicts** — coarse, but a stream of them still implies presence
   and wellbeing state.
4. **The audit log** — reveals caregiver behaviour.

## 3. Actors

| Actor | Trusted? | Notes |
|---|---|---|
| Resident (monitored person) | n/a — the protected party | Holds the consent control and may read the audit log |
| Caregiver | partially | Needs alerts; must not get raw data; access is logged |
| Local network observer | no | On the home LAN or ISP path |
| Network/destination operator | no | Sees transport metadata |
| Device-physical attacker | no | Physical access to the in-home node |

## 4. Threats addressed (and the mechanism that addresses each)

| Threat | Mechanism | Evidence |
|---|---|---|
| Over-collection: caregiver side accrues raw behavioural data | `MinimalVerdict` schema — only 5 coarse fields can cross the boundary | Experiment C1: 8640 raw values/day vs 5 fields/verdict (1728× reduction) |
| Monitoring a person without their control | `ConsentGate` — resident can pause; paused ⇒ no verdict accepted or shown | Experiment C2: an URGENT verdict is rejected while paused |
| Indefinite retention of sensitive raw data | `RetentionPolicy` — raw days older than the window are purged | Experiment C3: 7 of 15 days purged at the cutoff |
| Opaque, asymmetric surveillance | `AuditLog` — every caregiver access is recorded and readable by the resident | Audit summary in Part A results |
| Local network observer reading the stream | VPN / Tor transports encrypt the path | Part B transport comparison |

## 5. Threats deliberately NOT solved (state honestly; do not overclaim)

- **A caregiver who is themselves the threat.** The model assumes the
  caregiver is a benign recipient. A caregiver who legitimately holds
  dashboard access but misuses alert information is *not* stopped by this
  system — only made auditable. This is a real residual risk.
- **Global passive network adversary.** Tor reduces, but does not eliminate,
  de-anonymization: an adversary observing both ends can still correlate
  traffic timing. Verdicts are emitted on a daily cadence, which itself
  leaks coarse timing.
- **Physical access to the in-home device.** Anyone with the device can read
  raw data before retention purges it. Disk encryption / tamper resistance
  is out of scope for this prototype.
- **Inference from the verdict stream.** Even minimal verdicts, observed over
  time, reveal presence and wellbeing trends. Minimization reduces but does
  not erase this.
- **The detector is not validated.** False positives (e.g. the benign-atypical
  day, which both models escalate) mean alerts can mislead a caregiver.

## 6. Ethical review checklist

Before any use beyond the synthetic-data lab setting, all of the following
must hold:

- [ ] **Informed consent** of the monitored resident, in a form they
      understand, renewable and revocable.
- [ ] **Resident control** is real: the consent pause is accessible to the
      resident without going through the caregiver.
- [ ] **No third-party sensing.** Sensors must not capture visitors or
      neighbours; the brief forbids surveillance of third parties.
- [ ] **Access scoping.** Each caregiver has a named identity; access is
      logged; the resident can review the log.
- [ ] **Retention limit** is configured and enforced; a manual purge/delete
      path exists for the resident.
- [ ] **Data minimization** is enforced in code (the verdict schema), not
      left to operator discipline.
- [ ] **No policy evasion.** Transport choices (VPN/Tor) are configured by
      the operator within institutional rules; the system does not script
      circumvention.
- [ ] **Honest claims.** Reports describe a prototype evaluated on synthetic
      data over a short window — not a production or clinical system.
- [ ] **Failure modes disclosed** to anyone relying on alerts: false
      positives and false negatives both occur.

## 7. Residual risk statement

Hearth reduces over-collection, gives the resident a real off-switch, limits
retention, and makes caregiver access transparent. It does **not** make
monitoring risk-free: a trusted-but-malicious caregiver, traffic correlation
against Tor, physical device access, and detector error all remain. Any
deployment decision must weigh the wellbeing benefit against these residual
risks with the monitored person as the deciding party.
