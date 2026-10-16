RedAlarm premium time-picker integration kit
Target branch: yashh-tech-patch-2

WHAT THIS DOES
- Replaces the existing alarm edit UI with the two-page premium time picker/settings UI.
- Keeps the existing app alarm store and scheduler as the source of truth.
- Adds a save confirmation with alarm details, then returns to the home screen.
- Shows a home-screen toast: "Alarm set for __ hours and __ minutes from now".
- Preserves ringtone selection and adds selected volume to preview/ring playback.
- Adds redalarm_timepicker.py and replaces the old AlarmEditScreen KV layout.

BEFORE APPLYING
1. Download/extract this ZIP.
2. Open PowerShell in your local RedAlarm repository folder.
3. Check out branch: git switch yashh-tech-patch-2
4. Make sure main.py and alarm.kv have no uncommitted changes. The installer refuses to overwrite dirty files.
5. Copy these three files from the extracted ZIP into the SAME FOLDER as the installer:
   - apply_redalarm_timepicker_integration.py
   - redalarm_timepicker_payload.py
   - validate_redalarm_timepicker_integration.py

APPLY
Run from the RedAlarm repository root:
  python C:\path\to\extracted\apply_redalarm_timepicker_integration.py

The installer checks the branch and expected source anchors, creates a backup folder next to the repository, writes main.py/alarm.kv and adds redalarm_timepicker.py. It does NOT commit or push.

VALIDATE
From the repository root:
  python -m py_compile main.py redalarm_timepicker.py
  git diff --check
  python C:\path\to\extracted\validate_redalarm_timepicker_integration.py
  python main.py

Review the UI and test creating an alarm, saving, returning home, sound preview, local sound selection, volume, snooze and dismiss before committing.

COMMIT WHEN LOCAL TESTING PASSES
  git status
  git diff -- main.py alarm.kv
  git add main.py alarm.kv redalarm_timepicker.py
  git commit -m "Integrate premium alarm time picker"
  git push origin yashh-tech-patch-2

If anything goes wrong, the installer prints the backup folder path; restore main.py and alarm.kv from that backup and remove the newly added redalarm_timepicker.py.
