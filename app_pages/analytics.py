from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database.db import get_daily_reflections, get_focus_sessions
from services.analytics_service import calculate_analytics
from services.productivity_service import build_focus_profile
from services.timer_service import format_duration


def readable_total(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


st.title("Focus analytics")
st.caption("A modest view of the focus time recorded on this device.")

sessions = get_focus_sessions()
if not sessions:
    st.info(
        "No analytics yet. Save a focus session to begin building a picture.",
        icon=":material/analytics:",
    )
    st.stop()

metrics = calculate_analytics(sessions)
profile = build_focus_profile(sessions, get_daily_reflections())

with st.container(horizontal=True):
    st.metric(
        "Focused today", readable_total(int(metrics["today_seconds"])), border=True
    )
    st.metric(
        "Focused this week", readable_total(int(metrics["week_seconds"])), border=True
    )
    st.metric("Completed sessions", int(metrics["completed_count"]), border=True)
    st.metric(
        "Average session", format_duration(int(metrics["average_seconds"])), border=True
    )

st.subheader("Personal focus coach")
with st.container(horizontal=True):
    st.metric(
        "Suggested focus block",
        f"{profile['suggested_minutes']} min",
        border=True,
    )
    st.metric(
        "Strongest time",
        profile["best_period"] or "Learning",
        border=True,
    )
    st.metric(
        "Actual vs planned",
        (
            f"{profile['plan_accuracy']:.0%}"
            if profile["plan_accuracy"] is not None
            else "Learning"
        ),
        border=True,
    )
    st.metric("Sessions learned from", profile["sample_size"], border=True)

if profile["sample_size"] < 5:
    st.caption(
        "Recommendations become more reliable after at least five completed focus sessions."
    )
elif profile["plan_accuracy"] is not None:
    if profile["plan_accuracy"] > 1.15:
        st.info(
            "Your sessions tend to run longer than planned. Consider increasing task "
            "estimates or leaving more buffer.",
            icon=":material/lightbulb:",
        )
    elif profile["plan_accuracy"] < 0.7:
        st.info(
            "You often use less time than planned. Smaller initial focus blocks may make "
            "the day easier to size accurately.",
            icon=":material/lightbulb:",
        )

coach_left, coach_right = st.columns(2)
with coach_left:
    if profile["period_stats"]:
        with st.container(border=True):
            st.subheader("Focus by time of day")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Period": period,
                            "Sessions": stats["sessions"],
                            "Completion": stats["completion_rate"],
                            "Average minutes": stats["average_minutes"],
                        }
                        for period, stats in profile["period_stats"].items()
                    ]
                ),
                hide_index=True,
                column_config={
                    "Completion": st.column_config.NumberColumn(
                        "Completion", format="percent"
                    )
                },
            )
with coach_right:
    if profile["mood_focus_minutes"]:
        with st.container(border=True):
            st.subheader("Focus by mood")
            st.caption("Average focused minutes on days with a saved mood.")
            mood_labels = {1: "Rough", 2: "Low", 3: "Okay", 4: "Good", 5: "Great"}
            st.bar_chart(
                pd.DataFrame(
                    [
                        {"Mood": mood_labels[mood], "Minutes": minutes}
                        for mood, minutes in profile["mood_focus_minutes"].items()
                    ]
                ),
                x="Mood",
                y="Minutes",
            )

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Sessions by outcome")
        outcome_frame = pd.DataFrame(
            [
                {"Outcome": status.title(), "Sessions": count}
                for status, count in metrics["by_status"].items()
            ]
        )
        st.bar_chart(outcome_frame, x="Outcome", y="Sessions")

with right:
    with st.container(border=True):
        st.subheader("Focus time by project")
        project_frame = pd.DataFrame(
            [
                {"Project": project, "Hours": round(seconds / 3600, 2)}
                for project, seconds in metrics["by_project"].items()
            ]
        )
        st.bar_chart(project_frame, x="Project", y="Hours", horizontal=True)

with st.container(border=True):
    st.subheader("Daily focus time")
    today = date.today()
    start = today - timedelta(days=13)
    daily_seconds = metrics["by_day"]
    daily_frame = pd.DataFrame(
        [
            {
                "Date": start + timedelta(days=offset),
                "Minutes": round(
                    daily_seconds.get(start + timedelta(days=offset), 0) / 60, 1
                ),
            }
            for offset in range(14)
        ]
    )
    st.line_chart(daily_frame, x="Date", y="Minutes")
