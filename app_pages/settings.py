from __future__ import annotations

import streamlit as st

from database.db import get_database_path
from services.settings_service import (
    CredentialStoreError,
    credential_store_label,
    get_todoist_token,
    get_todoist_token_source,
    remove_todoist_token,
    save_todoist_token,
)
from services.todoist_service import TodoistService, TodoistServiceError


def reset_todoist_state() -> None:
    st.session_state.todoist_tasks = []
    st.session_state.todoist_projects = []
    st.session_state.todoist_loaded = False
    st.session_state.todoist_error = None
    st.session_state.habits_loaded = False
    st.session_state.habit_history_checked = False


st.title("Settings")
st.caption("Choose how Focus connects and see where your local data is stored.")

token = get_todoist_token()
source = get_todoist_token_source()

st.subheader("Todoist")
if token:
    st.success("Todoist is connected.", icon=":material/check_circle:")
else:
    st.info(
        "Todoist is not connected. All local features continue to work.",
        icon=":material/cloud_off:",
    )

with st.expander(
    "Connect or replace Todoist token",
    icon=":material/link:",
    expanded=not bool(token),
):
    st.link_button(
        "Open Todoist API token page",
        "https://app.todoist.com/app/settings/integrations/developer",
        icon=":material/open_in_new:",
    )
    with st.form("todoist_connection_settings"):
        new_token = st.text_input(
            "Todoist API token",
            type="password",
            help=f"Saved securely in {credential_store_label()}.",
        )
        connect = st.form_submit_button(
            "Test and save connection",
            type="primary",
            icon=":material/save:",
        )
    if connect:
        try:
            with st.spinner("Checking the connectionâ€¦"):
                TodoistService(new_token).get_projects()
                save_todoist_token(new_token)
            reset_todoist_state()
            st.toast("Todoist connected.", icon=":material/check:")
            st.rerun()
        except (ValueError, TodoistServiceError, CredentialStoreError) as exc:
            st.error(str(exc), icon=":material/error:")

if source == "environment":
    st.caption(
        "Todoist is supplied by the developer environment. Remove it from `.env` "
        "to use the connection controls here."
    )
elif token:
    if st.button("Disconnect Todoist", icon=":material/link_off:"):
        try:
            remove_todoist_token()
            reset_todoist_state()
            st.toast("Todoist disconnected. Focus is now in local mode.")
            st.rerun()
        except CredentialStoreError as exc:
            st.error(str(exc), icon=":material/error:")

st.subheader("Local data")
st.write("Timers, tasks, habits, goals, and journal entries are stored on this computer.")
st.code(str(get_database_path()), language=None)
st.caption("Use Data Health to create backups or download a JSON archive.")
