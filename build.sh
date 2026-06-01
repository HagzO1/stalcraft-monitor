#!/usr/bin/env bash
set -e

echo "=== Stalcraft Monitor APK Builder ==="
echo ""

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required"; exit 1; }
command -v java >/dev/null 2>&1 || { echo "ERROR: Java JDK 17+ required"; exit 1; }

# Install buildozer if not present
if ! command -v buildozer &>/dev/null; then
    echo "Installing buildozer..."
    pip install --upgrade pip setuptools wheel cython buildozer
fi

echo "Starting build (this will take 20-40 min on first run)..."
echo ""

export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
buildozer android debug

echo ""
echo "=== Done! APK in bin/ ==="
ls -lh bin/*.apk 2>/dev/null || echo "No APK found"
