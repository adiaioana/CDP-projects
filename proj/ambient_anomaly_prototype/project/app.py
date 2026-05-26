"""
app.py
------
Minimal Streamlit dashboard for the anomaly detection prototype.

Run with:
    streamlit run app.py
"""

from __future__ import annotations
import os

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from preprocessing import load_events, hourly_features
from anomaly_detection import detect_all


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data", "sensor_events.csv")


SEVERITY_COLOR = {
    "low":    "#f4c542",
    "medium": "#e07b39",
    "high":   "#c0392b",
    "info":   "#5b8def",
}


@st.cache_data
def load():
    events = load_events(DATA_PATH)
    feats  = hourly_features(events)
    alerts, model_out = detect_all(feats)
    return events, feats, alerts, model_out.scored


def main():
    st.set_page_config(page_title="Ambient Anomaly Detector", layout="wide")
    st.title("🏠 Ambient Smart-Home Anomaly Detection")
    st.caption(
        "A privacy-preserving research prototype. "
        "Anonymized sensor IDs only — no audio, video, or identity data."
    )

    events, feats, alerts, scored = load()

    # ---------- summary metrics ----------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total events",         f"{len(events):,}")
    c2.metric("Hours observed",       f"{len(feats):,}")
    c3.metric("Alerts raised",        f"{len(alerts):,}")
    c4.metric("Days covered",         f"{feats['date'].nunique()}")

    # ---------- date filter ----------
    st.divider()
    available_dates = sorted(feats["date"].unique())
    default_start = available_dates[max(0, len(available_dates) - 7)]
    date_range = st.slider(
        "Date range",
        min_value=available_dates[0],
        max_value=available_dates[-1],
        value=(default_start, available_dates[-1]),
    )
    mask = (feats["date"] >= date_range[0]) & (feats["date"] <= date_range[1])
    feats_view = feats[mask]
    alerts_view = alerts[
        (alerts["timestamp"].dt.date >= date_range[0]) &
        (alerts["timestamp"].dt.date <= date_range[1])
    ]

    # ---------- activity timeline ----------
    st.subheader("Sensor activity timeline")
    fig, ax = plt.subplots(figsize=(12, 3.5))
    ax.plot(feats_view["hour_bin"], feats_view["event_count"],
            linewidth=1.2, color="#5b8def", label="events / hour")
    # overlay alerts as vertical lines
    for _, row in alerts_view.iterrows():
        ax.axvline(row["timestamp"],
                   color=SEVERITY_COLOR.get(row["severity"], "#888"),
                   alpha=0.55, linewidth=1.4)
    ax.set_xlabel("time")
    ax.set_ylabel("events / hour")
    ax.set_title("hourly event count (vertical lines = alerts, colored by severity)")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    st.pyplot(fig, clear_figure=True)

    # ---------- daily activity summary ----------
    st.subheader("Daily activity summary")
    daily = feats_view.groupby("date").agg(
        total_events=("event_count", "sum"),
        active_hours=("event_count", lambda s: int((s > 0).sum())),
        max_inactivity=("inactivity_hours", "max"),
        night_events=("event_count", lambda s: int(s[feats_view.loc[s.index, "is_night"] == 1].sum())),
    ).reset_index()
    st.dataframe(daily, use_container_width=True, hide_index=True)

    # ---------- alerts table ----------
    st.subheader("Detected anomalies")
    if alerts_view.empty:
        st.info("No alerts in the selected range.")
    else:
        # group by severity for clarity
        for sev in ["high", "medium", "low", "info"]:
            sub = alerts_view[alerts_view["severity"] == sev]
            if sub.empty:
                continue
            label = {"high": "🔴 High", "medium": "🟠 Medium",
                     "low": "🟡 Low", "info": "🔵 Info (model)"}[sev]
            with st.expander(f"{label} — {len(sub)} alert(s)", expanded=sev != "info"):
                st.dataframe(
                    sub[["timestamp", "type", "detail"]].sort_values("timestamp"),
                    use_container_width=True, hide_index=True,
                )

    # ---------- privacy footer ----------
    st.divider()
    with st.expander("🔒 Privacy & data minimization"):
        st.markdown(
            "- **Anonymized IDs only.** Sensors are labelled by room and device type "
            "(e.g. `MOTION_KITCHEN`), never by person.\n"
            "- **No audio or video** is captured or stored.\n"
            "- **Aggregation.** All modelling is done on 1-hour windows, "
            "not raw event sequences, which limits behavioural reconstruction.\n"
            "- **Local processing.** The prototype runs entirely on the host machine; "
            "no data leaves the device.\n"
            "- **Purpose limitation.** Data is used only to detect routine deviations; "
            "no identity inference is attempted."
        )


if __name__ == "__main__":
    main()
