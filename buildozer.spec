[app]
title = RedAlarm
package.name = redalarm
package.domain = org.systopic
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy

# If your java_src folder contains custom Java code for native Android alarms, uncomment the line below:
# android.add_src = java_src

orientation = portrait
fullscreen = 0
android.permissions = INTERNET, VIBRATE, WAKE_LOCK, RECEIVE_BOOT_COMPLETED
android.api = 33
android.minapi = 21
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1