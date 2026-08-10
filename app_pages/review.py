from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from database.db import (
    get_daily_plan,
    get_focus_sessions,
    get_habit_daily_checkins,
    get_habit_definitions,
    get_weekly_review,
    save_weekly_review,
)
from database.models import WeeklyReview
from services.datetime_service import local_timestamp
from services.productivity_service import calculate_weekly_metrics


def readable_minutes(minutes: float) -> str:
    hours, remaining = divmod(round(minutes), 60)
    return f"{hours}h {remaining}m" if hours else f"{remaining}m"


st.title("Weekly review")
st.caption("Review the evidence, name what happened, and make one useful adjustment.")

selected_date = st.date_input("Week containing", value=date.today())
week_start = selected_date - timedelta(days=selected_date.weekday())
week_end = week_start + timedelta(days=6)
st.caption(f"Monday {week_start.strftime('%b %d')} – Sunday {week_end.strftime('%b %d, %Y')}")

sessions = get_focus_sessions()
habits = get_habit_definitions()
checkins = get_habit_daily_checkins(since=week_start)
metrics = calculate_weekly_metrics(
    sessions,
    habits,
    checkins,
    week_start=week_start,
)

plan_items: list[dict[str, object]] = []
for offset in range(7):
    _, items = get_daily_plan(week_start + timedelta(days=offset))
    plan_items.extend(items)
planned_count = len(plan_items)
completed_plan_count = sum(str(item["status"]) == "completed" for item in plan_items)

with st.container(horizontal=True):
    st.metric(
        "Focused",
        readable_minutes(float(metrics["focus_seconds"]) / 60),
        border=True,
    )
    st.metric(
        "Completed sessions",
        f"{metrics['completed_sessions']}/{metrics['session_count']}",
        border=True,
    )
    st.metric(
        "Habit adherence",
        (
            f"{metrics['habit_done']}/{metrics['habit_due']}"
            if metrics["habit_due"]
            else "No scheduled days"
        ),
        border=True,
    )
    st.metric(
        "Planned tasks closed",
        f"{completed_plan_count}/{planned_count}",
        border=True,
    )

st.subheader("What the week says")
observations: list[str] = []
plan_ratio = metrics["plan_ratio"]
if plan_ratio is not None:
    if plan_ratio > 1.15:
        observations.append(
            "Focus sessions ran materially longer than planned; add more buffer or use larger estimates."
        )
    elif plan_ratio < 0.7:
        observations.append(
            "Actual focus time was well below planned session time; shorter commitments may be easier to finish."
        )
    else:
        observations.append("Planned and actual focus time were reasonably aligned.")
habit_rate = metrics["habit_rate"]
if habit_rate is not None:
    observations.append(f"Scheduled habit adherence was {habit_rate:.0%}.")
if metrics["by_project"]:
    top_project = next(iter(metrics["by_project"]))
    observations.append(f"{top_project} received the most focus time.")
if not observations:
    observations.append("There is not enough activity yet for a data-based observation.")
for observation in observations:
    st.markdown(f"- {observation}")

if metrics["by_project"]:
    with st.container(border=True):
        st.subheader("Focus allocation")
        st.bar_chart(
            pd.DataFrame(
                [
                    {"Project": project, "Hours": round(seconds / 3600, 2)}
                    for project, seconds in metrics["by_project"].items()
                ]
            ),
            x="Project",
            y="Hours",
            horizontal=True,
        )

saved_review = get_weekly_review(week_start)
with st.form(f"weekly_review_{week_start.isoformat()}"):
    rating = st.segmented_control(
        "How did the week feel?",
        [1, 2, 3, 4, 5],
        default=saved_review.rating if saved_review else 3,
        format_func=lambda score: {1: "Rough", 2: "Hard", 3: "Okay", 4: "Good", 5: "Great"}[score],
    )
    wins = st.text_area(
        "Wins",
        value=saved_review.wins if saved_review else "",
        max_chars=2_000,
        placeholder="What moved forward?",
    )
    blockers = st.text_area(
        "Blockers",
        value=saved_review.blockers if saved_review else "",
        max_chars=2_000,
        placeholder="What repeatedly got in the way?",
    )
    adjustments = st.text_area(
        "One or two adjustments for next week",
        value=saved_review.adjustments if saved_review else "",
        max_chars=2_000,
        placeholder="Protect mornings, reduce the plan, change a habit schedule…",
    )
    save_clicked = st.form_submit_button(
        "Save weekly review",
        type="primary",
        icon=":material/save:",
    )
if save_clicked:
    save_weekly_review(
        WeeklyReview(
            week_start=week_start,
            rating=int(rating),
            wins=wins,
            blockers=blockers,
            adjustments=adjustments,
            updated_at=datetime.now(timezone.utc),
        )
    )
    st.toast("Weekly review saved.", icon=":material/check:")
    st.rerun()

if saved_review:
    st.caption(f"Last saved {local_timestamp(saved_review.updated_at).strftime('%b %d at %I:%M %p').replace(' 0', ' ')}")
