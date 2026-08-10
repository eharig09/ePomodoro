from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from services.timer_service import TimerState, format_duration


OUTCOME_LABELS = {
    "Completed": "The planned work for this focus session was completed.",
    "Continue": "The session went well, but more work remains on the task.",
    "Interrupted": "An external interruption prevented the intended work.",
    "Abandoned": "The session was intentionally stopped.",
}


@dataclass(frozen=True, slots=True)
class SessionSummarySubmission:
    submitted: bool
    status: str = ""
    notes: str = ""


def render_session_summary(state: TimerState) -> SessionSummarySubmission:
    actual = state.final_actual_seconds or 0
    st.subheader("How did this focus session go?")
    st.caption(
        f"{format_duration(actual)} focused · {state.planned_minutes} minutes planned. "
        "Saving the session will not complete the Todoist task."
    )

    default_outcome = "Completed" if state.completion_reason == "natural" else "Continue"
    with st.form(f"session_summary_{state.session_uuid}", border=True):
        outcome = st.segmented_control(
            "Outcome",
            list(OUTCOME_LABELS),
            default=default_outcome,
            required=True,
            key=f"session_outcome_{state.session_uuid}",
        )
        if outcome:
            st.caption(OUTCOME_LABELS[str(outcome)])
        notes = st.text_area(
            "Session note (optional)",
            max_chars=500,
            placeholder="What moved forward?",
            key=f"session_notes_{state.session_uuid}",
        )
        submitted = st.form_submit_button(
            "Save focus session", type="primary", icon=":material/save:"
        )

    return SessionSummarySubmission(
        submitted=submitted,
        status=str(outcome).lower() if outcome else "",
        notes=notes,
    )

