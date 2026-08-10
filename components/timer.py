from __future__ import annotations

import streamlit as st

from services.session_service import checkpoint_timer
from services.timer_service import (
    PAUSED,
    RUNNING,
    TimerState,
    advance_timer,
    elapsed_seconds,
    format_duration,
    pause_timer,
    remaining_seconds,
    resume_timer,
    stop_timer,
    utc_now,
)


@st.fragment(run_every=1)
def render_timer(state: TimerState) -> None:
    now = utc_now()
    if advance_timer(state, now=now):
        checkpoint_timer(state, now=now, force=True)
        st.rerun()

    checkpoint_timer(state, now=now)

    remaining = remaining_seconds(state, now=now)
    elapsed = elapsed_seconds(state, now=now)

    with st.container(horizontal_alignment="center", gap="small"):
        if state.phase == PAUSED:
            st.badge("Paused", icon=":material/pause:", color="orange")
        else:
            st.caption(
                "Break in progress" if state.timer_type == "break" else "Focus in progress"
            )
        metric_label = "Break remaining" if state.timer_type == "break" else "Time remaining"
        st.metric(metric_label, format_duration(remaining), width="content")
        progress = elapsed / state.planned_seconds if state.planned_seconds else 0
        progress_text = (
            f"{format_duration(elapsed)} elapsed"
            if state.timer_type == "break"
            else f"{format_duration(elapsed)} focused"
        )
        st.progress(min(1.0, max(0.0, progress)), text=progress_text)

        with st.container(horizontal=True, horizontal_alignment="center"):
            if state.phase == RUNNING and st.button(
                "Pause", icon=":material/pause:", key="pause_timer"
            ):
                pause_timer(state)
                checkpoint_timer(state, force=True)
                st.rerun()
            if state.phase == PAUSED and st.button(
                "Resume",
                type="primary",
                icon=":material/play_arrow:",
                key="resume_timer",
            ):
                resume_timer(state)
                checkpoint_timer(state, force=True)
                st.rerun()
            if st.button(
                "Finish early / stop",
                icon=":material/stop:",
                key="stop_timer",
            ):
                stop_timer(state)
                checkpoint_timer(state, force=True)
                st.rerun()
