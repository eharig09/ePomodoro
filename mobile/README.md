# ePomodoro Mobile

The Android-first, local-first companion for ePomodoro. It is a separate Flutter
interface, so the existing Python/Streamlit desktop app remains unchanged.

## MVP features

- Local tasks and optional Todoist API v1 synchronization.
- Project columns sorted by Todoist priority, with Today and All Active views.
- Focus and break timers that survive backgrounding and checkpoint every five seconds.
- A gentle three-second completion chime.
- Editable and deletable focus history.
- Monday-first habit schedules, frequency-aware current and best streaks, and a
  weekly check/X table.
- Generic habits that count matching Todoist task names or any completed task
  carrying an assigned label. Sync checks the previous 45 days of Todoist history.
- Daily mood and quick-journal entry.
- Dark mode by default.
- SQLite data stored on the device. The optional Todoist token is stored through
  Android encrypted credential storage and is never included in an APK.
- Optional email/password accounts synchronize local tasks, focus history,
  habits, check-ins, moods, and journals with desktop while keeping a separate
  offline SQLite profile for every account.

Cloud sync is manual in this first release and must be configured by the app
administrator. Existing local data is copied into an account only when the user
explicitly chooses the one-time import option. Builds without cloud configuration
continue to work entirely in local mode.

## Build and test locally

Install the current stable Flutter SDK and Android development tools, then run:

```bash
cd mobile
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build apk --release
```

The installable file is written to
`build/app/outputs/flutter-apk/app-release.apk`.

## Build without installing Android tools

Run the repository's **Build Android APK** workflow from GitHub Actions. It pins
the Flutter framework revision used during development, runs formatting checks,
analysis, and tests, builds one universal APK, scans it for private runtime files,
creates a SHA-256 checksum, and uploads the result as `ePomodoro-Android`.

To enable accounts in the APK, add the repository variables `SUPABASE_URL` and
`SUPABASE_PUBLISHABLE_KEY` before running the workflow. See
`docs/cloud-sync-setup.md` for the backend migration and security setup.

Distributed APKs use one permanent signing certificate supplied through encrypted
GitHub Actions secrets. To update a phone, download the newer APK, open it, and
choose **Update**; Android preserves the app's local data. Each release must also
increase the numeric build suffix in `pubspec.yaml` (for example `+2` to `+3`).

APK builds created before version 0.2.0 used a disposable debug certificate and
cannot be updated in place. Those early builds must be uninstalled once before
installing 0.2.0. After that one-time transition, normal in-place updates work.

Publishing through Google Play can later use Play App Signing. Signing keys and
passwords must never be committed to this repository.
