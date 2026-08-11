from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

import streamlit as st

from database.db import (
    delete_calendar_source,
    get_calendar_sources,
    get_database_path,
    init_db,
    save_calendar_source,
)
from database.models import CalendarSource
from services.calendar_service import (
    CalendarServiceError,
    count_calendar_events,
    fetch_calendar_ics,
    normalize_calendar_url,
)
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
    get_calendar_feed_urls,
    get_todoist_token,
    get_todoist_token_source,
    remove_todoist_token,
    remove_calendar_feed_url,
    save_calendar_feed_url,
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
        "Sign in to keep tasks, focus history, habits, check-ins, goals, and journal entries "
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
                value=True,
                help=(
                    "Recommended when this computer already contains data. The account "
                    "profile is merged with cloud data after the copy."
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
                synchronize_cloud(account, profile_path)
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
                    profile_path = activate_cloud_profile(
                        session.user_id, import_local=True
                    )
                    init_db(profile_path)
                    synchronize_cloud(account, profile_path)
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
            "Sync now", type="primary", icon=":material/sync:", width="stretch"
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
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            try:
                remove_cloud_session()
                restore_local_profile()
                reset_profile_state()
                st.rerun()
            except CloudAccountError as exc:
                st.error(str(exc), icon=":material/error:")
    st.caption(
        "Sync runs automatically after sign-in and can also be started here. For security, "
        "Todoist tokens do not cloud-sync; paste the same token once on each device."
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

st.subheader("Calendar availability")
st.caption(
    "Connect a private read-only iCalendar link or import an ICS file. Focus caches "
    "events on this device to find open time, but never adds or changes calendar events."
)
calendar_sources = get_calendar_sources()
calendar_urls = get_calendar_feed_urls()
provider_names = {
    "Google Calendar": "google",
    "Outlook / Microsoft 365": "outlook",
    "Other iCalendar feed": "ics",
}

with st.expander(
    "Add another calendar link" if calendar_sources else "Connect a calendar link",
    icon=":material/calendar_add_on:",
    expanded=not bool(calendar_sources),
):
    if calendar_sources:
        st.caption(
            "Each Google or Outlook calendar has its own ICS link. Add Work, "
            "Personal, or any other calendar separately; ePomodoro merges the "
            "selected calendars when finding open time."
        )
    with st.container(horizontal=True):
        st.link_button(
            "Google iCal instructions",
            "https://support.google.com/calendar/answer/37648",
            icon=":material/open_in_new:",
        )
        st.link_button(
            "Outlook publish instructions",
            "https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com",
            icon=":material/open_in_new:",
        )
    st.warning(
        "A private calendar link can reveal your schedule. Keep it secret and reset it "
        "in Google or Outlook if it is ever shared accidentally.",
        icon=":material/key:",
    )
    with st.form("calendar_feed_connection"):
        provider_label = st.selectbox("Provider", list(provider_names))
        calendar_name = st.text_input(
            "Calendar name",
            max_chars=120,
            placeholder="Work calendar",
        )
        calendar_url = st.text_input(
            "Private ICS link",
            type="password",
            placeholder="https://.../calendar.ics",
            help=(
                f"Stored in {credential_store_label()} and never included in "
                "account sync or exports. Replace webcal:// with https:// if needed."
            ),
        )
        connect_calendar = st.form_submit_button(
            "Test and connect",
            type="primary",
            icon=":material/link:",
        )
    if connect_calendar:
        source_id = str(uuid4())
        try:
            if not calendar_name.strip():
                raise ValueError("Enter a calendar name")
            with st.spinner("Checking the read-only calendar feed..."):
                normalized_calendar_url = normalize_calendar_url(calendar_url)
                ics_data = fetch_calendar_ics(normalized_calendar_url)
                event_count = count_calendar_events(ics_data)
                timestamp = datetime.now(timezone.utc)
                source = CalendarSource(
                    id=source_id,
                    name=calendar_name.strip(),
                    provider=provider_names[provider_label],
                    event_count=event_count,
                    last_refreshed_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                save_calendar_source(source, ics_data)
                try:
                    save_calendar_feed_url(source_id, normalized_calendar_url)
                except Exception:
                    delete_calendar_source(source_id)
                    raise
            st.toast("Read-only calendar connected.", icon=":material/check:")
            st.rerun()
        except (
            CalendarServiceError,
            CredentialStoreError,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            st.error(str(exc), icon=":material/error:")
            st.caption(
                "The correct link normally ends in `.ics` or is labeled Secret "
                "address / ICS link by the provider. You can also import an exported "
                "ICS file below."
            )

with st.expander("Import an ICS snapshot", icon=":material/upload_file:"):
    st.caption(
        "Imported files are snapshots. Re-import the file when its events change."
    )
    with st.form("calendar_file_import"):
        imported_name = st.text_input(
            "Imported calendar name",
            max_chars=120,
            placeholder="School schedule",
        )
        uploaded_calendar = st.file_uploader(
            "ICS file",
            type=["ics"],
        )
        import_calendar = st.form_submit_button(
            "Import calendar",
            icon=":material/upload:",
        )
    if import_calendar:
        try:
            if not imported_name.strip():
                raise ValueError("Enter a calendar name")
            if uploaded_calendar is None:
                raise ValueError("Choose an ICS file")
            raw_data = uploaded_calendar.getvalue()
            if len(raw_data) > 5_000_000:
                raise ValueError("Calendar files must be smaller than 5 MB")
            ics_data = raw_data.decode("utf-8-sig")
            event_count = count_calendar_events(ics_data)
            timestamp = datetime.now(timezone.utc)
            save_calendar_source(
                CalendarSource(
                    id=str(uuid4()),
                    name=imported_name.strip(),
                    provider="ics",
                    event_count=event_count,
                    last_refreshed_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
                ics_data,
            )
            st.toast("Calendar snapshot imported.", icon=":material/check:")
            st.rerun()
        except (UnicodeDecodeError, CalendarServiceError, ValueError, sqlite3.Error) as exc:
            st.error(str(exc), icon=":material/error:")

if calendar_sources:
    st.caption(
        f"Connected on this device: {len(calendar_sources)} calendar"
        f"{'s' if len(calendar_sources) != 1 else ''}."
    )
    for source in calendar_sources:
        with st.container(border=True):
            with st.container(
                horizontal=True,
                horizontal_alignment="distribute",
                vertical_alignment="center",
            ):
                st.markdown(f"**{source.name}**")
                st.badge(
                    source.provider.title(),
                    icon=":material/calendar_month:",
                    color="blue",
                )
            st.caption(
                f"{source.event_count} source event(s) cached. Last refreshed "
                f"{source.last_refreshed_at.astimezone().strftime('%b %d at %I:%M %p').replace(' 0', ' ')}."
            )
            with st.container(horizontal=True):
                if source.id in calendar_urls and st.button(
                    "Refresh",
                    key=f"refresh_calendar_{source.id}",
                    icon=":material/refresh:",
                ):
                    try:
                        with st.spinner(f"Refreshing {source.name}..."):
                            ics_data = fetch_calendar_ics(calendar_urls[source.id])
                            timestamp = datetime.now(timezone.utc)
                            save_calendar_source(
                                replace(
                                    source,
                                    event_count=count_calendar_events(ics_data),
                                    last_refreshed_at=timestamp,
                                    updated_at=timestamp,
                                ),
                                ics_data,
                            )
                        st.toast(f"{source.name} refreshed.")
                        st.rerun()
                    except (CalendarServiceError, OSError, sqlite3.Error) as exc:
                        st.error(str(exc), icon=":material/error:")
                if st.button(
                    "Remove",
                    key=f"remove_calendar_{source.id}",
                    icon=":material/delete:",
                ):
                    try:
                        remove_calendar_feed_url(source.id)
                        delete_calendar_source(source.id)
                        st.toast(f"{source.name} removed from this device.")
                        st.rerun()
                    except (CredentialStoreError, sqlite3.Error) as exc:
                        st.error(str(exc), icon=":material/error:")

st.subheader("Local data")
st.write("Timers, tasks, habits, goals, and journal entries are stored on this computer.")
st.code(str(get_database_path()), language=None)
st.caption("Use Data Health to create backups or download a JSON archive.")
