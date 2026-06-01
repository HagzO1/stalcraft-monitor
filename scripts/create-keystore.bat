@echo off
set KEYSTORE_FILE=stalcraft-release.keystore
set KEY_ALIAS=stalcraft
set VALIDITY=10000

echo === Stalcraft Monitor Keystore Generator ===
echo.
if exist "%KEYSTORE_FILE%" (
    echo WARNING: %KEYSTORE_FILE% already exists!
    set /p confirm="Overwrite? (y/N): "
    if /i not "!confirm!"=="y" exit /b
)

keytool -genkey -v -keystore "%KEYSTORE_FILE%" -alias "%KEY_ALIAS%" -keyalg RSA -keysize 2048 -validity %VALIDITY%

echo.
echo === Done! ===
echo Run scripts\encode-keystore.ps1 to get base64 for GitHub Secrets.
echo.
echo Add these secrets to GitHub:
echo   KEYSTORE_BASE64   — run encode-keystore.ps1
echo   KEYSTORE_ALIAS    — %KEY_ALIAS%
echo   KEYSTORE_PASSWORD — your keystore password
echo   KEY_PASSWORD      — your key password
