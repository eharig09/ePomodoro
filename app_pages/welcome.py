from __future__ import annotations

import streamlit as st

from database.db import set_app_setting
from services.settings_service import (
    CredentialStoreError,
    credential_store_label,
    save_todoist_token,
)
from services.todoist_service import TodoistService, TodoistServiceError


def finish_setup() -> None:
    set_app_setting("onboarding_complete", "1")
    st.session_state.todoist_loaded = False
    st.session_state.habits_loaded = False
    st.session_state.habit_history_checked = False


st.title("Welcome to Focus")
st.caption("A private productivity workspace that runs on this computer.")

st.write(
    "You can use focus timers, local tasks, habits, goals, reviews, and analytics "
    "without creating an account. Todoist is an optional connection."
)

local_column, todoist_column = st.columns(2, gap="large")

with local_column:
    with st.container(border=True):
        st.subheader("Use without Todoist")
        st.write("Start immediately. You can connect Todoist later from Settings.")
        if st.button(
            "Start in local mode",
            type="primary",
            icon=":material/arrow_forward:",
            width="stretch",
        ):
            finish_setup()
            st.rerun()

with todoist_column:
    with st.container(border=True):
        st.subheader("Connect Todoist")
        st.write("Bring in tasks and count linked task completions toward habits.")
        st.link_button(
            "Open Todoist API token page",
            "https://app.todoist.com/app/settings/integrations/developer",
            icon=":material/open_in_new:",
            width="stretch",
        )
        with st.form("welcome_todoist_connection"):
            token = st.text_input(
                "Todoist API token",
                type="password",
                help=(
                    f"The token is saved in {credential_store_label()}, not in "
                    "the app database."
                ),
            )
            submitted = st.form_submit_button(
                "Connect and continue",
                icon=":material/link:",
                width="stretch",
            )
        if submitted:
            try:
                with st.spinner("Checking the connectionâ€¦"):
                    TodoistService(token).get_projects()
                    save_todoist_token(token)
                finish_setup()
                st.rerun()
            except (ValueError, TodoistServiceError, CredentialStoreError) as exc:
                st.error(str(exc), icon=":material/error:")

st.caption(
    "Your productivity history stays in a local database on this computer. "
    "Focus never bundles or displays your Todoist token."
)
