[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

requirements=python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype,charset-normalizer>=2.1.1

orientation = portrait
fullscreen = 0

# API 34 is a safer target for the current python-for-android toolchain.
android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a

android.accept_sdk_license = True

# ========== ANDROID PERMISSIONS ==========
# Required permissions for alarm functionality on Android 12+
android.permissions = SCHEDULE_EXACT_ALARM,SET_ALARM,RECEIVE_BOOT_COMPLETED,WAKE_LOCK,INTERNET,POST_NOTIFICATIONS

# Required for Android 12+ - declare which alarms will be scheduled
android.uses_feature = android.hardware.alarm

# ========== MANIFEST & JAVA ==========
p4a.bootstrap = sdl2

# Manifest additions for alarm receiver and notification permissions
android.manifest_additions = <uses-feature android:name="android.hardware.alarm" android:required="false" /><receiver android:name="org.kivy.android.KivyAlarmReceiver" android:exported="true"><intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /><action android:name="android.intent.action.SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED" /></intent-filter></receiver>

# ========== JAVA SOURCE ==========
android.add_src = java_src/

[buildozer]

log_level = 2
warn_on_root = 0
