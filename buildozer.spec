[app]
title = Stalcraft Monitor
package.name = stalcraftmonitor
package.domain = org.stalcraft.monitor
source.dir = .
source.include_exts = py,png,jpg,jpeg,gif,json,kv,ttf
version = 1.0.0
requirements = python3,kivy==2.3.1,kivy-garden.matplotlib,stalcraft-api>=2.1.0,aiogram>=3.0.0,Pillow>=10.0.0,aiofiles>=23.0.0,aiohttp==3.9.5,matplotlib>=3.5.0,numpy
orientation = portrait
osx.pocket_version = 2.0
fullscreen = 0
icon = icon.png
android.api = 33
android.minapi = 24
android.release_artifact = apk
android.gradle_repositories = maven { url 'https://artifactory-external.vkpartner.ru/artifactory/rustore/' }
android.gradle_dependencies = ru.rustore.sdk:ads:3.4.0

[buildozer]
log_level = 2
warn_on_root = 1

[app:android]
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.sdk = 33
android.ndk = 25.2.9519653
android.accept_sdk_license = True
android.archs = arm64-v8a
android.wakelock = True
android.allow_backup = True
android.enable_androidx = True
android.manifest_minsdk = 21
android.manifest_targetsdk = 33
android.keystore = $(KEYSTORE_PATH)
android.keystore_alias = $(KEYSTORE_ALIAS)
android.keystore_password = $(KEYSTORE_PASSWORD)
android.keyalias_password = $(KEY_PASSWORD)

[app:ios]
ios.codesign.debug =
ios.codesign.release =
ios.codesign.all = False
