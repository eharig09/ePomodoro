# Read-only calendar setup

ePomodoro can read Google Calendar, Outlook/Microsoft 365, or another standard
ICS calendar. It uses the events only to identify open focus windows and preview
where tasks from the saved daily plan fit. It never creates, edits, or deletes a
calendar event.

## Google Calendar

1. Open Google Calendar on a computer.
2. Open **Settings**, choose the calendar under **Settings for my calendars**,
   then choose **Integrate calendar**.
3. Copy the **Secret address in iCal format**.
4. In ePomodoro, open **Settings > Calendar availability**, choose Google
   Calendar, and paste the link.

Google documents these steps in
[Sync your calendar with computer programs](https://support.google.com/calendar/answer/37648).
Treat the secret address like a password. Reset it in Google if it is ever shared.

## Outlook or Microsoft 365

1. In Outlook Calendar, open **Settings > Calendar > Shared calendars**.
2. Under **Publish a calendar**, select a calendar and read-only permission.
3. Choose **Publish** and copy the ICS link.
4. In ePomodoro, open **Settings > Calendar availability**, choose Outlook /
   Microsoft 365, and paste the link.

Microsoft documents this in
[Share your calendar in Outlook.com](https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com).
Some work or school administrators disable calendar publishing. The ICS file
upload option remains available when an exported file can be obtained.

## Privacy and refresh behavior

- Private subscription URLs are stored in Windows Credential Manager, macOS
  Keychain, or the system credential store.
- URLs never enter ePomodoro account sync or JSON exports.
- Cached calendar event data and availability preferences remain in the local
  profile database, so the last refresh works offline.
- A local database backup or complete JSON archive can contain cached event
  details. Store exports and backups securely.
- Remote feeds refresh only when **Refresh** is selected in Settings or on the
  Calendar page. Imported ICS files are snapshots and must be re-imported when
  they change.
