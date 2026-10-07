[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

requirements = python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype

orientation = portrait
fullscreen = 0

android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a

# All Android behavior is implemented in main.py. No extra Java/manifest
# source files are required for this build.
android.permissions = WAKE_LOCK,USE_EXACT_ALARM,VIBRATE,POST_NOTIFICATIONS,USE_FULL_SCREEN_INTENT,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

# Reuse the existing Activity so Android alarm/notification action intents
# arrive through onNewIntent when the app is already running.
android.manifest.launch_mode = singleTask

android.presplash_color = #0B0910
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
