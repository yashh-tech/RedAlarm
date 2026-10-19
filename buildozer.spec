[app]

title = RedAlarm
icon.filename = %(source.dir)s/redalarm_icon.png
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf
# Do not bundle development/patch helpers or the launcher icon a second time.
source.exclude_dirs = tests
source.exclude_patterns = RedAlarm_TimePicker_Test.py,TimePicker_Test.py,TimePicker_Test2.py,gemini_timepicker.py,apply_redalarm_timepicker_integration.py,validate_redalarm_timepicker_integration.py,apply_redalarm_launcher_icon_only.py,redalarm_timepicker_payload.py,apply_redalarm_comprehensive_fix.py,redalarm_icon.png

version = 1.0.0

# Keep this minimal. Do not add charset-normalizer.
requirements = python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype

orientation = portrait

# Native Android splash colour shown before Python even starts, so there
# is no white flash - it matches the in-app RedAlarm splash.
presplash.filename = %(source.dir)s/presplash2.png
android.presplash_color = #000000
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
# POST_NOTIFICATIONS               -> required on API 33+ to show the
#                                    alarm-ringing (Dismiss/Snooze) notification
# USE_FULL_SCREEN_INTENT          -> lets the ringing notification launch the
#                                    alarm screen over the lock screen
# VIBRATE                          -> per-alarm vibration
# SYSTEM_ALERT_WINDOW               -> "display over other apps"; some OEM
#                                    skins (MIUI/ColorOS/etc.) want this
#                                    granted before they'll let a
#                                    backgrounded app pop an activity
android.permissions = WAKE_LOCK,SCHEDULE_EXACT_ALARM,USE_EXACT_ALARM,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,POST_NOTIFICATIONS,SYSTEM_ALERT_WINDOW,VIBRATE,USE_FULL_SCREEN_INTENT,RECEIVE_BOOT_COMPLETED,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK

# CRITICAL for alarms: without this, Android stacks a new copy of the
# activity on top every time AlarmManager fires while the app is already
# open, instead of reusing the one instance and routing it through
# onNewIntent (which is what main.py's android.activity.bind hook needs).
android.manifest.launch_mode = singleTask

# Only genuine ringing intents get lock-screen visibility; native receiver
# restores alarms after reboot/time/time-zone changes without launching Home.
android.add_src = java_src,android_src
# Independent ringtone playback that continues if the Kivy Activity is stopped.
services = ring:services/ring_service.py:foreground:sticky:foregroundServiceType=mediaPlayback
p4a.hook = java_src/manifest_hook.py
android.extra_manifest_application_arguments = ./extra_manifest_application_arguments.xml

android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 0
