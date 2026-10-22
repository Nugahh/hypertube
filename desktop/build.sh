#!/bin/sh
# Builds the macOS app: desktop/release/Hypertube-*.dmg. Needs Node, Python 3.11+ and an Internet connection.
set -eu
cd "$(dirname "$0")"
ARCH="$(uname -m)"
STAGE="$PWD/stage"
rm -rf "$STAGE" && mkdir -p "$STAGE/bin"

echo "== the site"
(cd ../frontend && npm ci --silent && npm run build --silent)
cp -R ../frontend/dist "$STAGE/frontend"

echo "== the back (PyInstaller)"
PY="${PYTHON:-python3.11}"
[ -d build/venv ] || "$PY" -m venv build/venv
grep -v '^psycopg\|^pytest' ../backend/requirements.txt > build/req-desktop.txt
build/venv/bin/pip -q install -r build/req-desktop.txt pyinstaller
build/venv/bin/pyinstaller --noconfirm --clean --onedir --name hypertube-backend --paths ../backend \
  --collect-submodules uvicorn --collect-submodules app --collect-all libtorrent \
  --distpath build/dist --workpath build/work --specpath build/work backend_entry.py > /dev/null
cp -R build/dist/hypertube-backend "$STAGE/backend"

echo "== Jackett"
if [ "$ARCH" = "arm64" ]; then JACKETT="Jackett.Binaries.macOSARM64.tar.gz"; else JACKETT="Jackett.Binaries.macOS.tar.gz"; fi
mkdir -p build/jackett-dl
[ -f "build/jackett-dl/$JACKETT" ] || curl -fL -o "build/jackett-dl/$JACKETT" "https://github.com/Jackett/Jackett/releases/latest/download/$JACKETT"
tar -xzf "build/jackett-dl/$JACKETT" -C build/jackett-dl
cp -R build/jackett-dl/Jackett "$STAGE/jackett"

echo "== ffmpeg"
npm install --silent
cp node_modules/ffmpeg-static/ffmpeg "$STAGE/bin/ffmpeg"
PLATFORM="$([ "$ARCH" = arm64 ] && echo arm64 || echo x64)"
cp "node_modules/@ffprobe-installer/darwin-$PLATFORM/ffprobe" "$STAGE/bin/ffprobe"
chmod +x "$STAGE/bin/ffmpeg" "$STAGE/bin/ffprobe"

echo "== the .dmg"
npx electron-builder --mac dmg
ls -lh release/*.dmg
