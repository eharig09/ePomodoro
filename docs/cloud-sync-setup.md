# Multi-user cloud sync setup

ePomodoro uses Supabase Auth, Postgres, and row-level security while preserving a
local SQLite database on every device. Cloud sync is optional: without the two
public configuration values, desktop and Android continue in local-only mode.

## 1. Create the backend

1. Create a Supabase project.
2. Open the SQL editor and run
   `supabase/migrations/202608110001_multi_user_sync.sql`, followed by
   `supabase/migrations/202608110002_sync_goals.sql`, then
   `supabase/migrations/202608110003_sync_planning.sql`.
3. In Authentication > Providers > Email, keep email/password enabled.
4. Keep email confirmation enabled for public use. Configure custom SMTP before
   a production launch; Supabase's trial sender is intentionally rate limited.
5. Copy the project URL and **publishable** key from the project's API settings.

Never use or distribute a `service_role` or secret key. The applications only
accept the publishable key; user JWTs plus row-level security provide access.

## 2. Configure desktop development

Add these public values to the ignored `.env` file:

```dotenv
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_your-key
```

Packaged desktop builds can receive the same variables from their launch
environment. They are identifiers, not privileged server credentials.

## 3. Configure Android builds

Pass the public values as Dart defines:

```bash
flutter build apk --release \
  --dart-define=SUPABASE_URL=https://your-project-ref.supabase.co \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=sb_publishable_your-key
```

The GitHub Android workflow reads repository variables named `SUPABASE_URL` and
`SUPABASE_PUBLISHABLE_KEY`. Builds without them remain fully usable in local mode.

## Sync behavior

- Each signed-in account gets a separate local profile database.
- Existing local-only data is imported after the user-approved copy option and
  safely merged when the account profile already exists.
- Local writes remain immediate and work offline.
- Sync sends changed records, pulls remote changes, and retains deletion
  tombstones so deletes propagate to other devices.
- Focus sessions and habit check-ins have stable IDs and merge independently.
- Conflicting edits use deterministic last-write-wins based on client timestamp,
  with device ID as a tie-breaker.
- Todoist tokens never enter sync records and remain in each device's secure vault.

This protocol synchronizes local tasks, focus history, habits, habit check-ins,
moods, journals, desktop goals with their links, daily plans and rituals, weekly
objectives, and weekly reviews. Android ignores planning and goal records it does
not yet display without deleting them from the account; those views remain
desktop/browser-only for now.

Calendar subscription links, cached ICS event data, and availability preferences
are intentionally device-local and do not enter account sync.
