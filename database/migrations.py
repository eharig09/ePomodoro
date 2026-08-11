from __future__ import annotations

import sqlite3


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_uuid TEXT NOT NULL UNIQUE,
            todoist_task_id TEXT NOT NULL,
            task_name TEXT NOT NULL,
            project_id TEXT,
            project_name TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            planned_minutes INTEGER NOT NULL CHECK (planned_minutes > 0),
            actual_seconds INTEGER NOT NULL CHECK (actual_seconds >= 0),
            status TEXT NOT NULL CHECK (
                status IN ('completed', 'continue', 'interrupted', 'abandoned')
            ),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_focus_sessions_started_at
            ON focus_sessions(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_focus_sessions_project
            ON focus_sessions(project_id);
        CREATE INDEX IF NOT EXISTS idx_focus_sessions_status
            ON focus_sessions(status);

        CREATE TABLE IF NOT EXISTS interruptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (session_id) REFERENCES focus_sessions(id) ON DELETE CASCADE
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS local_focus_tasks (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            project_name TEXT NOT NULL DEFAULT 'Local',
            priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 4),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_local_focus_tasks_active
            ON local_focus_tasks(completed_at, created_at DESC);
        """,
    ),
    (
        3,
        """
        ALTER TABLE focus_sessions
            ADD COLUMN is_provisional INTEGER NOT NULL DEFAULT 0
            CHECK (is_provisional IN (0, 1));

        CREATE INDEX IF NOT EXISTS idx_focus_sessions_provisional
            ON focus_sessions(is_provisional);
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS habits (
            todoist_task_id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            project_id TEXT,
            project_name TEXT NOT NULL,
            recurrence TEXT NOT NULL,
            priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 4),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_habits_active
            ON habits(is_active, project_name, content);

        CREATE TABLE IF NOT EXISTS habit_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todoist_task_id TEXT NOT NULL,
            completed_on TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('app', 'todoist')),
            FOREIGN KEY (todoist_task_id) REFERENCES habits(todoist_task_id)
                ON DELETE CASCADE,
            UNIQUE(todoist_task_id, completed_on)
        );

        CREATE INDEX IF NOT EXISTS idx_habit_checkins_date
            ON habit_checkins(completed_on DESC);
        """,
    ),
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS habit_definitions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            group_name TEXT NOT NULL DEFAULT 'Habits',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_habit_definitions_active
            ON habit_definitions(is_active, group_name, name);

        CREATE TABLE IF NOT EXISTS habit_task_links (
            habit_id TEXT NOT NULL,
            todoist_task_id TEXT NOT NULL,
            content TEXT NOT NULL,
            project_id TEXT,
            project_name TEXT NOT NULL,
            recurrence TEXT,
            priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 4),
            PRIMARY KEY (habit_id, todoist_task_id),
            FOREIGN KEY (habit_id) REFERENCES habit_definitions(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_habit_task_links_task
            ON habit_task_links(todoist_task_id);

        CREATE TABLE IF NOT EXISTS habit_label_links (
            habit_id TEXT NOT NULL,
            label TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (habit_id, label),
            FOREIGN KEY (habit_id) REFERENCES habit_definitions(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_habit_label_links_label
            ON habit_label_links(label COLLATE NOCASE);

        CREATE TABLE IF NOT EXISTS habit_daily_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id TEXT NOT NULL,
            completed_on TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            source TEXT NOT NULL CHECK (
                source IN ('habits', 'focus', 'todoist', 'migration')
            ),
            todoist_task_id TEXT,
            todoist_task_name TEXT,
            FOREIGN KEY (habit_id) REFERENCES habit_definitions(id)
                ON DELETE CASCADE,
            UNIQUE(habit_id, completed_on)
        );

        CREATE INDEX IF NOT EXISTS idx_habit_daily_checkins_date
            ON habit_daily_checkins(completed_on DESC);

        INSERT OR IGNORE INTO habit_definitions (
            id, name, group_name, is_active, created_at, updated_at
        )
        SELECT
            'legacy:' || todoist_task_id,
            content,
            project_name,
            is_active,
            created_at,
            updated_at
        FROM habits;

        INSERT OR IGNORE INTO habit_task_links (
            habit_id, todoist_task_id, content, project_id, project_name,
            recurrence, priority
        )
        SELECT
            'legacy:' || todoist_task_id,
            todoist_task_id,
            content,
            project_id,
            project_name,
            recurrence,
            priority
        FROM habits;

        INSERT OR IGNORE INTO habit_daily_checkins (
            habit_id, completed_on, completed_at, source,
            todoist_task_id, todoist_task_name
        )
        SELECT
            'legacy:' || checkins.todoist_task_id,
            checkins.completed_on,
            checkins.completed_at,
            'migration',
            checkins.todoist_task_id,
            habits.content
        FROM habit_checkins AS checkins
        JOIN habits ON habits.todoist_task_id = checkins.todoist_task_id;
        """,
    ),
    (
        6,
        """
        ALTER TABLE habit_definitions
            ADD COLUMN scheduled_weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6';
        """,
    ),
    (
        7,
        """
        CREATE TABLE IF NOT EXISTS habit_group_settings (
            group_name TEXT PRIMARY KEY COLLATE NOCASE,
            emoji TEXT NOT NULL DEFAULT '✨',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_reflections (
            entry_date TEXT PRIMARY KEY,
            mood INTEGER NOT NULL CHECK (mood BETWEEN 1 AND 5),
            journal TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_daily_reflections_date
            ON daily_reflections(entry_date DESC);
        """,
    ),
    (
        8,
        """
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            target_date TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'completed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_goals_status
            ON goals(status, target_date, name);

        CREATE TABLE IF NOT EXISTS goal_links (
            goal_id TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('task', 'habit')),
            entity_id TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            PRIMARY KEY (goal_id, entity_type, entity_id),
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_goal_links_entity
            ON goal_links(entity_type, entity_id);

        CREATE TABLE IF NOT EXISTS task_preferences (
            task_id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            energy_level TEXT NOT NULL DEFAULT 'medium'
                CHECK (energy_level IN ('low', 'medium', 'high')),
            estimated_minutes INTEGER NOT NULL DEFAULT 25
                CHECK (estimated_minutes BETWEEN 1 AND 1440),
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_plans (
            plan_date TEXT PRIMARY KEY,
            energy_level TEXT NOT NULL DEFAULT 'medium'
                CHECK (energy_level IN ('low', 'medium', 'high')),
            available_minutes INTEGER NOT NULL DEFAULT 240
                CHECK (available_minutes BETWEEN 1 AND 1440),
            shutdown_time TEXT NOT NULL DEFAULT '17:00',
            intention TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_plan_items (
            plan_date TEXT NOT NULL,
            task_id TEXT NOT NULL,
            task_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('todoist', 'local')),
            position INTEGER NOT NULL DEFAULT 0,
            is_top_three INTEGER NOT NULL DEFAULT 0 CHECK (is_top_three IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned', 'completed', 'deferred')),
            PRIMARY KEY (plan_date, task_id),
            FOREIGN KEY (plan_date) REFERENCES daily_plans(plan_date)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_daily_plan_items_date
            ON daily_plan_items(plan_date, position);

        CREATE TABLE IF NOT EXISTS weekly_reviews (
            week_start TEXT PRIMARY KEY,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            wins TEXT NOT NULL DEFAULT '',
            blockers TEXT NOT NULL DEFAULT '',
            adjustments TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('success', 'error')),
            item_count INTEGER NOT NULL DEFAULT 0,
            matched_count INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_sync_runs_started
            ON sync_runs(started_at DESC);
        """,
    ),
    (
        9,
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        10,
        """
        CREATE TABLE IF NOT EXISTS cloud_sync_shadow (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            client_updated_at TEXT NOT NULL,
            device_id TEXT NOT NULL,
            deleted_at TEXT,
            PRIMARY KEY (entity_type, entity_id)
        );

        CREATE TABLE IF NOT EXISTS cloud_sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
    ),
    (
        11,
        """
        CREATE TABLE IF NOT EXISTS daily_rituals (
            ritual_date TEXT PRIMARY KEY,
            startup_completed_at TEXT,
            shutdown_completed_at TEXT,
            wins TEXT NOT NULL DEFAULT '',
            blockers TEXT NOT NULL DEFAULT '',
            tomorrow_first_task_id TEXT,
            tomorrow_first_task_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_daily_rituals_date
            ON daily_rituals(ritual_date DESC);

        CREATE TABLE IF NOT EXISTS weekly_plans (
            week_start TEXT PRIMARY KEY,
            objectives TEXT NOT NULL DEFAULT '',
            intention TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_weekly_plans_start
            ON weekly_plans(week_start DESC);
        """,
    ),
    (
        12,
        """
        CREATE TABLE IF NOT EXISTS calendar_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL CHECK (
                provider IN ('google', 'outlook', 'ics')
            ),
            ics_data TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
            last_refreshed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_calendar_sources_refreshed
            ON calendar_sources(last_refreshed_at DESC);
        """,
    ),
)


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row[0] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        with connection:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
