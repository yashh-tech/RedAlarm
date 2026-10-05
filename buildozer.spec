[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

# Pinned versions to avoid dependency conflicts in p4a build
requirements = python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype,charset-normalizer==2.1.1

orientation = portrait
fullscreen = 0

# API 34 is a safer target for the current python-for-android toolchain.
android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a

# WAKE_LOCK                        -> keep the CPU alive while ringing
# SCHEDULE_EXACT_ALARM/USE_EXACT_ALARM -> required on API 31+/33+ so the
#                                    alarm fires at the exact minute
# REQUEST_IGNORE_BATTERY_OPTIMIZATIONS -> lets the in-app banner open the
#                                    "don't optimize this app" screen
# POST_NOTIFICATIONS               -> required on API 33+ even though we
#                                    only use it defensively right now
android.permissions = WAKE_LOCK,SCHEDULE_EXACT_ALARM,USE_EXACT_ALARM,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,POST_NOTIFICATIONS

# CRITICAL for alarms: without this, Android stacks a new copy of the
# activity on top every time AlarmManager fires while the app is already
# open, instead of reusing the one instance and routing it through
# onNewIntent (which is what main.py's android.activity.bind hook needs).
android.manifest.launch_mode = singleTask

android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 0
