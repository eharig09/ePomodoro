from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

from database.db import get_app_setting, init_db, record_sync_run
from services.audio_service import ambient_noise
from services.cloud_account_service import activate_stored_cloud_profile
from services.habit_service import sync_completed_habit_history
from services.health_service import create_database_backup
from services.settings_service import get_todoist_token
from services.timer_service import RUNNING
from services.todoist_service import TodoistServiceError


load_dotenv(Path(__file__).resolve().parent / ".env")
activate_stored_cloud_profile()

DEFAULT_CALM_MUSIC_URL = "https://www.youtube.com/watch?v=X4VbdwhkE10"

st.set_page_config(
    page_title="Focus",
    page_icon=str(Path(__file__).resolve().parent / "assets" / "app_icon.png"),
    layout="wide",
    initial_sidebar_state="auto",
)

init_db()
todoist_token = get_todoist_token()
first_run = not todoist_token and get_app_setting("onboarding_complete") != "1"
try:
    automatic_backup_error = None
    create_database_backup(daily=True)
except (OSError, sqlite3.Error) as exc:
    automatic_backup_error = str(exc)

st.session_state.setdefault("todoist_tasks", [])
st.session_state.setdefault("todoist_projects", [])
st.session_state.setdefault("todoist_loaded", False)
st.session_state.setdefault("todoist_error", None)
st.session_state.setdefault("selected_task_id", None)
st.session_state.setdefault("active_timer", None)
st.session_state.setdefault("timer_sound_enabled", True)
st.session_state.setdefault("focus_audio_source", "Off")
st.session_state.setdefault("calm_music_url", DEFAULT_CALM_MUSIC_URL)
st.session_state.setdefault("focus_sort_by", "Priority")
st.session_state.setdefault("focus_group_by", "Project")
st.session_state.setdefault("habits_loaded", False)
st.session_state.setdefault("habit_completed_tasks", [])
st.session_state.setdefault("habit_sync_error", None)
st.session_state.setdefault("habit_history_checked", False)
st.session_state.setdefault("habit_history_sync_error", None)
st.session_state.setdefault("automatic_backup_error", automatic_backup_error)


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.netloc.lower() in {
        "youtube.com",
        "www.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }


with st.sidebar:
    if not first_run:
        connection_label = "Todoist connected" if todoist_token else "Local mode"
        st.caption(connection_label)
    with st.expander("Sound and appearance", icon=":material/graphic_eq:"):
        st.caption(
            f"{(st.context.theme.type or 'System').title()} theme. Switch Light/Dark from the "
            "app menu under Settings."
        )
        st.toggle(
            "Timer completion sound",
            key="timer_sound_enabled",
            persist_state="session",
        )
        audio_source = st.selectbox(
            "Focus audio source",
            ["Off", "White noise", "Pink noise", "Brown noise", "YouTube"],
            key="focus_audio_source",
            persist_state="session",
        )
        if audio_source.endswith("noise"):
            active_timer = st.session_state.active_timer
            focus_noise_active = (
                active_timer is not None
                and getattr(active_timer, "timer_type", "focus") == "focus"
                and getattr(active_timer, "phase", None) == RUNNING
            )
            if focus_noise_active:
                st.audio(
                    ambient_noise(audio_source.removesuffix(" noise").lower()),
                    format="audio/wav",
                    loop=True,
                    autoplay=True,
                )
                st.caption(f"{audio_source} is active for this focus timer.")
            else:
                st.caption(f"{audio_source} is ready and begins with a focus timer.")

        if audio_source == "YouTube":
            st.caption("YouTube is selected; local ambient noise is inactive.")
            music_url = st.text_input(
                "Calm music YouTube URL",
                placeholder="https://www.youtube.com/watch?v=…",
                key="calm_music_url",
                persist_state="session",
            )
            if music_url:
                if is_youtube_url(music_url):
                    st.link_button(
                        "Open selected YouTube audio",
                        music_url,
                        icon=":material/open_in_new:",
                        width="stretch",
                    )
                else:
                    st.caption("Enter a valid HTTPS YouTube or YouTube Music URL.")

    if os.getenv("FOCUS_DESKTOP") == "1" and st.button(
        "Exit Focus",
        icon=":material/power_settings_new:",
        help="Stops the local app. Your saved data is not affected.",
        width="stretch",
    ):
        os._exit(0)

if first_run:
    navigation_pages = [
        st.Page(
            "app_pages/welcome.py",
            title="Welcome",
            icon=":material/waving_hand:",
            default=True,
        )
    ]
else:
    navigation_pages = [
        st.Page(
            "app_pages/today.py",
            title="Today",
            icon=":material/today:",
            default=True,
        ),
        st.Page(
            "app_pages/focus.py",
            title="Focus",
            icon=":material/timer:",
        ),
        st.Page(
            "app_pages/habits.py",
            title="Habits",
            icon=":material/event_repeat:",
        ),
        st.Page(
            "app_pages/goals.py",
            title="Goals",
            icon=":material/flag:",
        ),
        st.Page(
            "app_pages/review.py",
            title="Review",
            icon=":material/rate_review:",
        ),
        st.Page(
            "app_pages/history.py",
            title="History",
            icon=":material/history:",
        ),
        st.Page(
            "app_pages/analytics.py",
            title="Analytics",
            icon=":material/analytics:",
        ),
        st.Page(
            "app_pages/health.py",
            title="Health",
            icon=":material/health_and_safety:",
        ),
        st.Page(
            "app_pages/settings.py",
            title="Settings",
            icon=":material/settings:",
        ),
    ]

page = st.navigation(
    navigation_pages,
    position="top",
)

if not st.session_state.habit_history_checked:
    token = get_todoist_token()
    if token:
        try:
            with st.spinner("Checking Todoist habit history…"):
                completed_tasks, matched_count = sync_completed_habit_history(
                    token,
                    now=datetime.now(timezone.utc),
                )
            st.session_state.habit_completed_tasks = completed_tasks
            st.session_state.habit_history_sync_error = None
            record_sync_run(
                "habit history",
                status="success",
                item_count=len(completed_tasks),
                matched_count=matched_count,
            )
        except TodoistServiceError as exc:
            st.session_state.habit_history_sync_error = str(exc)
            record_sync_run("habit history", status="error", message=str(exc))
    st.session_state.habit_history_checked = True

page.run()
