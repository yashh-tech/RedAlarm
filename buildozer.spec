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

# Alarm-clock delivery / active ringing behavior.
android.permissions = WAKE_LOCK,USE_EXACT_ALARM,VIBRATE,POST_NOTIFICATIONS,USE_FULL_SCREEN_INTENT,RECEIVE_BOOT_COMPLETED,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

# Native alarm receiver is compiled into the APK and registered below.
android.add_src = java_src
android.extra_manifest_application_arguments = %(source.dir)s/java_src/manifest_receiver_snippet.xml

# Intentional minimal presplash while the Kivy UI initializes.
android.presplash_color = #0B0910

# Reuse the existing activity and route alarm/action intents through onNewIntent.
android.manifest.launch_mode = singleTask

android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
