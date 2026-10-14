[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

# Keep this minimal. Do not add charset-normalizer.
requirements = python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype
services = ring:services/ring_service.py:foreground:sticky:foregroundServiceType=mediaPlayback

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
android.permissions = WAKE_LOCK,SCHEDULE_EXACT_ALARM,USE_EXACT_ALARM,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,POST_NOTIFICATIONS,SYSTEM_ALERT_WINDOW,USE_FULL_SCREEN_INTENT,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK,RECEIVE_BOOT_COMPLETED,VIBRATE
android.add_src = java_src,android_src
p4a.hook = java_src/manifest_hook.py
android.manifest.launch_mode = singleTask


android.extra_manifest_application_arguments = ./extra_manifest_application_arguments.xml
android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 0
