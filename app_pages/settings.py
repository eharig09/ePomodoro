from __future__ import annotations

import sqlite3

import streamlit as st

from database.db import get_database_path, init_db
from services.cloud_account_service import (
    CloudAccountError,
    CloudAccountService,
    CloudConfig,
    CloudConfigurationError,
    activate_cloud_profile,
    get_cloud_session,
    remove_cloud_session,
    restore_local_profile,
)
from services.cloud_sync_service import synchronize_cloud
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


def reset_profile_state() -> None:
    """Drop cached UI data after switching the active local profile."""
    for key in (
        "todoist_tasks",
        "todoist_projects",
        "selected_task_id",
        "active_timer",
        "habits_loaded",
        "habit_completed_tasks",
        "habit_history_checked",
        "habit_history_sync_error",
    ):
        st.session_state.pop(key, None)
    reset_todoist_state()


st.title("Settings")
st.caption("Choose how Focus connects and see where your local data is stored.")

st.subheader("Account and sync")
try:
    cloud_config = CloudConfig.from_environment()
    cloud_config_error = None
except CloudConfigurationError as exc:
    cloud_config = None
    cloud_config_error = str(exc)

cloud_session = get_cloud_session()
if cloud_config_error:
    st.error(cloud_config_error, icon=":material/error:")
elif cloud_config is None:
    st.info(
        "This installation is in local-only mode. An app administrator can add "
        "the Supabase URL and publishable key to enable accounts.",
        icon=":material/cloud_off:",
    )
elif cloud_session is None:
    st.write(
        "Sign in to keep tasks, focus history, habits, check-ins, and reflections "
        "in sync across your computers and Android devices."
    )
    sign_in_tab, create_tab = st.tabs(["Sign in", "Create account"])
    with sign_in_tab:
        with st.form("cloud_sign_in"):
            sign_in_email = st.text_input("Email", key="cloud_sign_in_email")
            sign_in_password = st.text_input(
                "Password", type="password", key="cloud_sign_in_password"
            )
            import_on_sign_in = st.checkbox(
                "Copy this device's current local data into my account",
                help=(
                    "Use this once if this computer already contains the data you want. "
                    "Existing account data on this device is left unchanged."
                ),
            )
            sign_in_clicked = st.form_submit_button(
                "Sign in", type="primary", icon=":material/login:"
            )
        if sign_in_clicked:
            try:
                account = CloudAccountService(cloud_config)
                session = account.sign_in(sign_in_email, sign_in_password)
                profile_path = activate_cloud_profile(
                    session.user_id, import_local=import_on_sign_in
                )
                init_db(profile_path)
                reset_profile_state()
                st.rerun()
            except (ValueError, CloudAccountError, OSError, sqlite3.Error) as exc:
                st.error(str(exc), icon=":material/error:")
    with create_tab:
        with st.form("cloud_sign_up"):
            sign_up_email = st.text_input("Email", key="cloud_sign_up_email")
            sign_up_password = st.text_input(
                "Password", type="password", key="cloud_sign_up_password"
            )
            create_clicked = st.form_submit_button(
                "Create account", type="primary", icon=":material/person_add:"
            )
        if create_clicked:
            try:
                account = CloudAccountService(cloud_config)
                session = account.sign_up(sign_up_email, sign_up_password)
                if session is None:
                    st.success(
                        "Account created. Check your email to confirm it, then sign in."
                    )
                else:
                    profile_path = activate_cloud_profile(session.user_id)
                    init_db(profile_path)
                    reset_profile_state()
                    st.rerun()
            except (ValueError, CloudAccountError, OSError, sqlite3.Error) as exc:
                st.error(str(exc), icon=":material/error:")
else:
    st.success(
        f"Signed in as {cloud_session.email or 'your account'}.",
        icon=":material/cloud_done:",
    )
    sync_col, sign_out_col = st.columns(2)
    with sync_col:
        if st.button(
            "Sync now", type="primary", icon=":material/sync:", use_container_width=True
        ):
            try:
                with st.spinner("Syncing your data…"):
                    summary = synchronize_cloud(CloudAccountService(cloud_config))
                st.success(
                    f"Synced {summary.pushed} local change(s) and received "
                    f"{summary.pulled} cloud record(s)."
                )
                reset_profile_state()
                st.rerun()
            except (CloudAccountError, OSError, ValueError, sqlite3.Error) as exc:
                st.error(str(exc), icon=":material/error:")
    with sign_out_col:
        if st.button(
            "Sign out", icon=":material/logout:", use_container_width=True
        ):
            try:
                remove_cloud_session()
                restore_local_profile()
                reset_profile_state()
                st.rerun()
            except CloudAccountError as exc:
                st.error(str(exc), icon=":material/error:")
    st.caption(
        "Sync is manual in this first release. Todoist tokens remain only on each device."
    )

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
