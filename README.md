# Focus productivity app

A local-first Streamlit productivity application with focus timers, tasks, habits,
goals, reviews, and analytics. It works entirely without an account; Todoist is an
optional connection for importing tasks and tracking linked completions.

## Easiest Windows setup

Download `Focus-Windows.zip`, choose **Extract all**, and double-click
`Focus.exe` in the extracted folder. The app opens in the default browser. No
Python, terminal, configuration file, or Todoist account is required. On the
first screen, choose **Start in local mode** or connect Todoist with an API token.

Packaged data is stored under `%LOCALAPPDATA%\Focus\data`. The Todoist token is
stored separately in Windows Credential Manager. Use **Exit Focus** in the
sidebar to stop the desktop app.

## Easiest Mac setup

Open `Focus-macOS-arm64.dmg` on an Apple silicon Mac (or the `x86_64` build on
an Intel Mac), drag **Focus** into Applications, and open it like any other Mac
app. No Python, Terminal, configuration file, or Todoist account is required.

Packaged Mac data is stored under `~/Library/Application Support/Focus/data`.
The optional Todoist token is stored separately in macOS Keychain. The current
Mac build configuration is ready, but the `.app` and `.dmg` must be compiled on
a Mac because PyInstaller does not cross-compile macOS applications from Windows.

## Android mobile app

The `mobile` directory contains an Android-first Flutter companion with local
SQLite storage, optional Todoist API v1 synchronization, focus and break timers,
scheduled habits and streaks, mood/journaling, and editable history. It uses a
separate mobile database, leaving the desktop application unchanged.

Run the **Build Android APK** GitHub Actions workflow to create one universal
`ePomodoro-Android.apk` that can be shared directly. See `mobile/README.md` for
the feature list, development commands, and current signing limitations.

## Features

- Optionally loads active Todoist tasks and projects through the official Python SDK.
- Shows every task due today or all active tasks without hiding projects.
- Sorts or groups the complete task view by priority or project.
- Supports SQLite-backed local focus tasks that never go to Todoist.
- Runs 15, 25, 50, or custom-length focus sessions without blocking the app.
- Includes 5, 10, 15, or custom break timers that stay out of focus analytics.
- Supports pause, resume, natural completion, and finishing early.
- Records Completed, Continue, Interrupted, or Abandoned outcomes with optional notes.
- Checkpoints active focus timers to SQLite as Continue every five focused seconds,
  so closing or refreshing the page does not discard the history row.
- Keeps focus completion separate from Todoist task completion.
- Provides filterable local history and basic project/status/daily analytics.
- Lets you correct or permanently delete saved history sessions.
- Handles missing or invalid tokens and network failures without crashing.
- Includes a subtle completion chime and locally generated white, pink, or brown noise.
- Can open a user-provided YouTube or YouTube Music URL in a separate tab.
- Defaults to a calm dark theme while retaining a light-mode option.

## Developer prerequisites

- Python 3.11 or newer is recommended.
- A Todoist account and API token only when testing the optional integration.
- Windows PowerShell for Windows development or a macOS shell for Mac development.

## Windows PowerShell setup

From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, allow scripts for the current process only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Configure Todoist for development (optional)

1. In Todoist, open **Settings → Integrations → Developer**.
2. Copy the API token shown there.
3. Open the local `.env` file and set:

```dotenv
TODOIST_API_TOKEN=your-token-here
```

Never commit `.env`. It is already excluded by `.gitignore`; `.env.example` contains only the variable name.

Without `.env`, the first-run screen lets you use local mode or save a token in
Windows Credential Manager or macOS Keychain.

## Run the app

With the virtual environment active:

```powershell
streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.

The app starts in dark mode. Use the app menu in the upper-right corner, then
**Settings**, to switch between the included Dark and Light themes.

## Local tasks and sound

Use **Add local task** on the Focus page for work that does not belong in
Todoist. Local tasks are stored only in `data/focus.db`, appear in both Today
and All active views, and can be completed independently.

The **Sound and appearance** panel in the sidebar provides:

- A toggle for the subtle timer-completion chime.
- One mutually exclusive **Focus audio source**: Off, White noise, Pink noise,
  Brown noise, or YouTube. Selecting YouTube removes and stops the local noise
  player before the YouTube link is launched.
- Locally generated white, pink, and brown noise. A 90-second WAV is generated
  in memory and loops in the browser; no audio service receives data. It starts
  only while a focus timer is running and stops when that timer is paused,
  stopped, or completed.
- A field for a YouTube or YouTube Music URL. The app opens it in another tab
  so music can continue while the Focus page remains visible. YouTube playback
  requires an internet connection and is subject to YouTube's own privacy and
  playback behavior. The default is `https://www.youtube.com/watch?v=X4VbdwhkE10`.

Browsers can block autoplay until the page has received a click. Starting a
timer normally provides the required interaction, but the ambient-noise player
can always be started manually.

Because YouTube opens in a separate browser tab, the app cannot pause an
already-playing YouTube video after it has opened. The source selector does
guarantee that this app's local noise and YouTube launcher are never active at
the same time.

## Run tests

```powershell
pytest
```

## Build the Windows executable

From PowerShell in the project directory:

```powershell
.\scripts\build_windows.ps1
```

The ready-to-share desktop build is written to `dist\Focus-Windows.zip`. It
bundles Python and all application dependencies. Keeping the runtime beside the
launcher avoids a long extraction delay on every start. The `.env` file and
local database are never included. Because this development build is not
code-signed, Windows may show an unknown-publisher warning on another computer.

## Build the macOS application

On the Mac that will produce the release, install Python 3.11 or newer and run:

```bash
bash scripts/build_macos.sh --clean
```

This creates `dist/Focus.app` and a disk image named for the Mac architecture,
such as `dist/Focus-macOS-arm64.dmg`. The build is ad-hoc signed by default and
is useful for local testing.

For a release that opens normally on someone else's Mac, install a **Developer
ID Application** certificate and create a `notarytool` keychain profile. Then run:

```bash
export FOCUS_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export FOCUS_NOTARY_PROFILE="focus-notary"
bash scripts/build_macos.sh --clean
```

The build script signs the collected app with hardened runtime, submits the DMG
to Apple's notary service, staples the resulting ticket, and asks Gatekeeper to
assess the finished disk image. Signing credentials are read from the Mac's
Keychain and environment; they are not stored in this project.

### Build Mac installers without owning a Mac

The manual GitHub Actions workflow in `.github/workflows/build-macos.yml` uses
hosted Apple-silicon and Intel Mac runners. After this project is in a GitHub
repository:

1. Open the repository's **Actions** tab.
2. Select **Build macOS installers**.
3. Choose **Run workflow**.
4. When both jobs finish, download `Focus-macOS-arm64` and
   `Focus-macOS-x86_64` from the run's Artifacts section.
5. Keep each `.sha256` file with its matching DMG when archiving a release.

Only the person downloading a workflow artifact needs a GitHub account and
repository access. The downloaded DMG can then be shared through any normal
file-sharing service. The workflow is manual-only and retains artifacts for 14
days. It runs the full test suite, launches the packaged app, checks its health
endpoint, and refuses to upload a bundle containing `.env` or `focus.db`.

GitHub builds are ad-hoc signed unless Apple Developer signing secrets are
configured separately. Ad-hoc builds are appropriate for testing; smooth
distribution to nontechnical users still requires Developer ID signing and
Apple notarization.

## Local data

During development, Focus history is stored in `data/focus.db`. The packaged
Windows app uses `%LOCALAPPDATA%\Focus\data\focus.db`; the Mac app uses
`~/Library/Application Support/Focus/data/focus.db`. Database tables and
migrations are applied automatically; no manual SQL is required.

The `focus_sessions` row stores Todoist IDs plus task/project snapshot text. History therefore remains understandable if a task is later renamed, moved, completed, or deleted in Todoist.

On the History page, select one table row to edit its task, project, session
time, planned minutes, actual focused minutes, outcome, or notes. Reducing
**Actual focus minutes** is useful when the timer continued while you were
pulled away. Deleting a session requires a separate confirmation and cannot be
undone.

## Refresh and close protection

Starting a focus timer immediately creates one provisional **Continue** session
in SQLite. Its actual focused time is refreshed every five seconds and on every
pause, stop, or timer completion. If the tab is closed, refreshed, or the app is
interrupted, that row is already available in History and can be corrected or
deleted there. Submitting the normal session outcome updates and finalizes the
same row, so it does not create a duplicate.

A browser refresh intentionally does not restart the live countdown. It files
the checkpoint under Continue, after which a new focus timer can be started.
Break timers are not checkpointed or added to focus history.

## Project structure

```text
app.py                     Streamlit entrypoint and navigation
desktop_launcher.py        Packaged Windows launcher
macos_launcher.py          Packaged macOS launcher
Focus.spec                 Portable Windows build definition
Focus-macOS.spec           macOS .app bundle definition
app_pages/                 Focus, History, and Analytics page scripts
components/                Task list, timer, and session summary UI
services/                  Todoist, timer, and analytics logic
database/                  SQLite models, access, and migrations
data/                      Local database location
tests/                     Focused unit and persistence tests
```

`app_pages/` is intentionally used instead of Streamlit's legacy `pages/` auto-discovery folder so routing is explicit through `st.navigation`.

## MVP limitations

- Active timer state is kept in the current Streamlit browser session. It survives normal widget and script reruns, but not a server restart or a closed browser tab.
- Task updates are pull-based through **Refresh tasks**; there are no webhooks or background sync.
- Breaks are intentionally not stored as focus sessions or included in analytics.
- Local tasks have a deliberately small lifecycle: add, focus, and complete; editing and reopening are not included yet.
- Detailed interruption events are not yet captured separately, although the database schema reserves an `interruptions` table.
- Analytics use the computer's local timezone and remain intentionally modest.
- No accounts, OAuth, notifications, mobile client, calendar integration, or cloud hosting are included.
