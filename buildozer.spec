[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

requirements=python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype,charset-normalizer

orientation = portrait
fullscreen = 0

# API 34 is a safer target for current python-for-android toolchain.
android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a

android.accept_sdk_license = True

# ========== ANDROID PERMISSIONS ==========
# Required permissions for alarm functionality on Android 12+
android.permissions = SCHEDULE_EXACT_ALARM,SET_ALARM,RECEIVE_BOOT_COMPLETED,WAKE_LOCK,INTERNET,POST_NOTIFICATIONS,FOREGROUND_SERVICE,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

# Required for Android 12+ - declare which alarms will be scheduled
android.uses_feature = android.hardware.alarm

# ========== MANIFEST & JAVA ==========
p4a.bootstrap = sdl2

# Manifest additions for alarm receiver, lockscreen wake, and service support
android.manifest_additions = <uses-feature android:name="android.hardware.alarm" android:required="false" /><uses-permission android:name="android.permission.FOREGROUND_SERVICE" /><service android:name="org.kivy.android.AlarmService" android:exported="false" android:foregroundServiceType="mediaPlayback" /><activity android:name="org.kivy.android.PythonActivity" android:exported="true" android:showWhenLocked="true" android:turnScreenOn="true" android:launchMode="singleTask" /><receiver android:name="org.kivy.android.KivyAlarmReceiver" android:exported="true" android:enabled="true"><intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /></intent-filter></receiver>

# ========== JAVA SOURCE ==========
android.add_src = java_src/

[buildozer]

log_level = 2
warn_on_root = 0
