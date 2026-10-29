"""Register RedAlarm's native alarm receiver and foreground ringing service."""
from pathlib import Path
import re


def after_apk_build(toolchain):
    dist = getattr(getattr(toolchain, "_dist", None), "dist_dir", None)
    if not dist:
        raise RuntimeError("python-for-android hook did not expose toolchain._dist.dist_dir")
    manifest = Path(dist) / "src" / "main" / "AndroidManifest.xml"
    if not manifest.is_file():
        raise RuntimeError("Generated AndroidManifest.xml was not found: " + str(manifest))
    text = manifest.read_text(encoding="utf-8")
    app = re.search(r"<application\b[^>]*>", text, flags=re.DOTALL)
    if app is None:
        raise RuntimeError("Could not find <application> in " + str(manifest))

    # Remove any previous versions of only the components owned by this hook,
    # then insert one canonical copy. This also repairs old manifests when p4a
    # reuses a build distribution.
    owned = [
        ("activity", "org.yashtech.redalarm.RedAlarmRingActivity"),
        ("receiver", "org.kivy.android.KivyAlarmReceiver"),
        ("receiver", "org.yashtech.redalarm.RedAlarmAlarmReceiver"),
        ("service", "org.yashtech.redalarm.RedAlarmRingingService"),
        ("receiver", "org.yashtech.redalarm.RedAlarmClockWidgetProvider"),
    ]
    for tag, name in owned:
        pattern = re.compile(r"\s*<" + tag + r"\b(?=[^>]*android:name=[\"']" + re.escape(name) + r"[\"'])[^>]*(?:/>|>.*?</" + tag + r"\s*>)", re.DOTALL)
        text = pattern.sub("", text)
    app = re.search(r"<application\b[^>]*>", text, flags=re.DOTALL)
    components = """
        <activity
            android:name="org.yashtech.redalarm.RedAlarmRingActivity"
            android:enabled="true"
            android:exported="false"
            android:launchMode="singleTask"
            android:taskAffinity="org.yashtech.redalarm.ring"
            android:excludeFromRecents="true"
            android:showWhenLocked="true"
            android:turnScreenOn="true" />
        <receiver android:name="org.kivy.android.KivyAlarmReceiver" android:enabled="true" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
                <action android:name="android.intent.action.TIME_SET" />
                <action android:name="android.intent.action.TIMEZONE_CHANGED" />
            </intent-filter>
        </receiver>
        <receiver android:name="org.yashtech.redalarm.RedAlarmAlarmReceiver" android:enabled="true" android:exported="false" />
        <service android:name="org.yashtech.redalarm.RedAlarmRingingService" android:enabled="true" android:exported="false" android:foregroundServiceType="mediaPlayback" />
        <receiver android:name="org.yashtech.redalarm.RedAlarmClockWidgetProvider" android:enabled="true" android:exported="true">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
                <action android:name="org.yashtech.redalarm.UPDATE_WIDGETS" />
            </intent-filter>
            <meta-data android:name="android.appwidget.provider" android:resource="@xml/redalarm_clock_widget_info" />
        </receiver>
"""
    text = text[:app.end()] + components + text[app.end():]
    manifest.write_text(text, encoding="utf-8")
    print("[RedAlarm] Registered alarm components and display-only home-screen widgets")


