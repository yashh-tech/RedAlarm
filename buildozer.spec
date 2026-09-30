[app]

title = RedAlarm
package.name = redalarm
package.domain = org.yashtech

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,mp3,wav,ogg,m4a,ttf,json

version = 1.0

requirements = python3,kivy,plyer

orientation = portrait

fullscreen = 0

android.api = 35
android.minapi = 23
android.ndk = 28b
android.archs = arm64-v8a

android.accept_sdk_license = True

# Icon - uncomment this only if the file actually exists
#icon.filename = %(source.dir)s/icon.png

# Presplash - uncomment this only if the file actually exists
#presplash.filename = %(source.dir)s/presplash.png

[buildozer]

log_level = 2
warn_on_root = 0