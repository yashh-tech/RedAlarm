[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,json,ttf

version = 1.0.0

# Keep this minimal. Do not add charset-normalizer.
requirements = python3==3.11.6,hostpython3==3.11.6,kivy==2.3.1,plyer,filetype,charset-normalizer==2.1.1

orientation = portrait
fullscreen = 0

# API 34 is a safer target for the current python-for-android toolchain.
android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a

android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 0