"""Register RedAlarm's receiver in the generated Android manifest."""

from pathlib import Path
import re


def before_apk_build(toolchain):
    manifest = Path("src/main/AndroidManifest.xml")

    if not manifest.is_file():
        raise RuntimeError(
            "Generated AndroidManifest.xml not found: "
            + str(manifest.resolve())
        )

    text = manifest.read_text(encoding="utf-8")
    receiver_name = "org.kivy.android.KivyAlarmReceiver"

    # Avoid adding the same receiver twice.
    if receiver_name in text:
        print("[RedAlarm] Receiver already registered")
        return

    application_open = re.search(
        r"<application\b[^>]*>",
        text,
        flags=re.DOTALL,
    )

    if application_open is None:
        raise RuntimeError(
            "Could not find <application> in AndroidManifest.xml"
        )

    receiver = """
        <receiver
            android:name="org.kivy.android.KivyAlarmReceiver"
            android:exported="true"
            android:enabled="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>
"""

    updated = (
        text[:application_open.end()]
        + receiver
        + text[application_open.end():]
    )

    manifest.write_text(updated, encoding="utf-8")
    print("[RedAlarm] Registered receiver in AndroidManifest.xml")
