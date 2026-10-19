"""Register RedAlarm's reboot receiver in the generated Android manifest.

python-for-android generates the Android project while processing the APK
arguments. The manifest does not exist yet during before_apk_build, so this
must run in after_apk_build, before Gradle assembles the APK.
"""

from pathlib import Path
import re


def after_apk_build(toolchain):
    """Insert the BOOT_COMPLETED receiver once the Android project exists."""
    dist = getattr(getattr(toolchain, "_dist", None), "dist_dir", None)
    if not dist:
        raise RuntimeError(
            "python-for-android hook did not expose toolchain._dist.dist_dir"
        )

    manifest = Path(dist) / "src" / "main" / "AndroidManifest.xml"
    if not manifest.is_file():
        raise RuntimeError(
            "Generated AndroidManifest.xml was not found after APK project "
            "generation: " + str(manifest)
        )

    text = manifest.read_text(encoding="utf-8")
    receiver_name = "org.kivy.android.KivyAlarmReceiver"

    # Be idempotent: never inject a duplicate receiver when a distribution
    # is reused or the hook is run more than once.
    if receiver_name in text:
        required_actions = (
            "android.intent.action.BOOT_COMPLETED",
            "android.intent.action.TIME_SET",
            "android.intent.action.TIMEZONE_CHANGED",
            "android.intent.action.MY_PACKAGE_REPLACED",
        )
        if all(action in text for action in required_actions):
            print("[RedAlarm] Receiver already registered and up to date")
            return
        text, removed = re.subn(
            r"\s*<receiver\b(?=[^>]*android:name=\"org\.kivy\.android\.KivyAlarmReceiver\")[^>]*>.*?</receiver>",
            "", text, count=1, flags=re.DOTALL,
        )
        if removed != 1:
            raise RuntimeError("Could not replace the stale KivyAlarmReceiver block")

    application_open = re.search(
        r"<application\b[^>]*>",
        text,
        flags=re.DOTALL,
    )
    if application_open is None:
        raise RuntimeError(
            "Could not find <application> in " + str(manifest)
        )

    receiver = """
        <receiver
            android:name="org.kivy.android.KivyAlarmReceiver"
            android:exported="true"
            android:enabled="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.TIME_SET" />
                <action android:name="android.intent.action.TIMEZONE_CHANGED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
            </intent-filter>
        </receiver>
"""

    updated = (
        text[:application_open.end()]
        + receiver
        + text[application_open.end():]
    )
    manifest.write_text(updated, encoding="utf-8")
    print("[RedAlarm] Registered KivyAlarmReceiver in AndroidManifest.xml")
