#!/usr/bin/env bash
set -e

KEYSTORE_FILE="stalcraft-release.keystore"
KEY_ALIAS="stalcraft"
VALIDITY=10000

echo "=== Stalcraft Monitor Keystore Generator ==="
echo ""
echo "This will create $KEYSTORE_FILE for signing the release AAB."
echo "Save the passwords — you need them for CI and future updates."
echo ""

if [ -f "$KEYSTORE_FILE" ]; then
    echo "WARNING: $KEYSTORE_FILE already exists!"
    read -p "Overwrite? (y/N): " confirm
    if [ "$confirm" != "y" ]; then exit 1; fi
fi

keytool -genkey -v \
    -keystore "$KEYSTORE_FILE" \
    -alias "$KEY_ALIAS" \
    -keyalg RSA \
    -keysize 2048 \
    -validity $VALIDITY

echo ""
echo "=== Done! ==="
echo "Now base64-encode the keystore for GitHub Secrets:"
echo "  base64 -w0 $KEYSTORE_FILE | pbcopy   # macOS"
echo "  base64 -w0 $KEYSTORE_FILE | xclip     # Linux"
echo ""
echo "Then add these secrets to https://github.com/$(git remote get-url origin 2>/dev/null | sed 's/.*://;s/\.git//')/settings/secrets/actions:"
echo "  KEYSTORE_BASE64  — base64 of the .keystore file"
echo "  KEYSTORE_ALIAS   — $KEY_ALIAS"
echo "  KEYSTORE_PASSWORD — your keystore password"
echo "  KEY_PASSWORD      — your key password"
