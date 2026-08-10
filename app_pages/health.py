from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from database.db import get_database_path, get_sync_runs
from services.datetime_service import format_local_datetime, local_timestamp
from services.health_service import (
    create_database_backup,
    database_integrity,
    export_database_json,
    list_database_backups,
    restore_database_backup,
)


st.title("Data health")
st.caption("See what synced, verify the local database, and keep recoverable copies.")

database_path = get_database_path()
integrity_ok, integrity_detail = database_integrity()
sync_runs = get_sync_runs(limit=50)
backups = list_database_backups()

if st.session_state.get("automatic_backup_error"):
    st.warning(
        "Today’s automatic backup could not be created. "
        f"{st.session_state.automatic_backup_error}",
        icon=":material/backup:",
    )

last_success = next((row for row in sync_runs if row["status"] == "success"), None)
with st.container(horizontal=True):
    st.metric(
        "Database",
        "Healthy" if integrity_ok else "Needs attention",
        border=True,
    )
    st.metric(
        "Database size",
        f"{database_path.stat().st_size / 1_048_576:.2f} MB",
        border=True,
    )
    st.metric("Backups", len(backups), border=True)
    st.metric(
        "Last successful sync",
        format_local_datetime(last_success["started_at"]) if last_success else "Not recorded",
        border=True,
    )

if integrity_ok:
    st.success("SQLite integrity check passed.", icon=":material/verified:")
else:
    st.error(f"SQLite integrity check failed: {integrity_detail}")

st.subheader("Todoist sync activity")
if sync_runs:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "When": local_timestamp(row["started_at"]),
                    "Type": row["sync_type"],
                    "Status": str(row["status"]).title(),
                    "Items": row["item_count"],
                    "Habit matches": row["matched_count"],
                    "Unmatched": (
                        max(0, int(row["item_count"]) - int(row["matched_count"]))
                        if row["sync_type"] in {"habits", "habit history"}
                        else None
                    ),
                    "Message": row["message"],
                }
                for row in sync_runs
            ]
        ),
        hide_index=True,
        column_config={
            "When": st.column_config.DatetimeColumn(
                "When", format="MMM DD, YYYY · h:mm a", pinned=True
            ),
            "Message": st.column_config.TextColumn("Message", width="large"),
        },
    )
else:
    st.info("No sync runs have been recorded yet.", icon=":material/sync:")

st.subheader("Backup and export")
with st.container(horizontal=True, vertical_alignment="center"):
    if st.button(
        "Create backup",
        type="primary",
        icon=":material/backup:",
    ):
        backup = create_database_backup()
        st.toast(f"Backup created: {backup.name}", icon=":material/check:")
        st.rerun()
    st.download_button(
        "Download JSON archive",
        data=export_database_json(),
        file_name=f"focus-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        mime="application/json",
        icon=":material/download:",
    )

backups = list_database_backups()
if backups:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Backup": backup.name,
                    "Created": datetime.fromtimestamp(backup.stat().st_mtime).astimezone(),
                    "Size MB": round(backup.stat().st_size / 1_048_576, 2),
                }
                for backup in backups
            ]
        ),
        hide_index=True,
        column_config={
            "Created": st.column_config.DatetimeColumn(
                "Created", format="MMM DD, YYYY · h:mm a"
            )
        },
    )

    restore_expander = st.expander(
        "Restore a backup", icon=":material/restore:", on_change="rerun"
    )
    if restore_expander.open:
        with restore_expander:
            st.warning(
                "Restoring replaces the current local database. A safety backup is "
                "created immediately before the restore.",
                icon=":material/warning:",
            )
            selected_backup = st.selectbox(
                "Backup",
                backups,
                format_func=lambda path: path.name,
            )
            confirm = st.checkbox("I understand that the current database will be replaced.")
            if st.button(
                "Restore selected backup",
                disabled=not confirm,
                type="primary",
                icon=":material/restore:",
            ):
                safety_backup = restore_database_backup(selected_backup)
                st.toast(
                    f"Backup restored. Safety copy: {safety_backup.name}",
                    icon=":material/check:",
                )
                st.rerun()

st.caption(f"Local database: {database_path}")
