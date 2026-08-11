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

The mobile and desktop databases are currently independent. Cross-device sync is
planned as a separate encrypted export/import or sync feature; silently combining
two local databases would risk overwriting history.

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

The MVP uses Android debug signing for direct installation. Publishing through
Google Play will require a private upload key and Play App Signing; those
credentials must never be committed to this repository.
