$file = "stalcraft-release.keystore"
if (-not (Test-Path $file)) {
    Write-Host "Keystore not found. Run scripts\create-keystore.bat first." -ForegroundColor Red
    exit 1
}
$bytes = [System.IO.File]::ReadAllBytes("$PWD\$file")
$b64 = [System.Convert]::ToBase64String($bytes)
Write-Host "Copy this into GitHub Secret KEYSTORE_BASE64:"
Write-Host ""
Write-Host $b64
