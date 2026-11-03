#!/bin/bash
# 在本机构建「仿真模型生成.app」并安装到 /Applications 与桌面
set -euo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="仿真模型生成.app"
BUILD_DIR="$PROJ/dist"
APP="$BUILD_DIR/$APP_NAME"
ICON_SRC="$PROJ/assets/logo.jpg"
ICNS="$PROJ/assets/AppIcon.icns"

if [ ! -f "$ICNS" ]; then
  ICONSET="$PROJ/assets/AppIcon.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  sips -s format png "$ICON_SRC" --out "$PROJ/assets/logo.png" >/dev/null
  for size in 16 32 128 256 512; do
    sips -z $size $size "$PROJ/assets/logo.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  done
  sips -z 32 32 "$PROJ/assets/logo.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 64 64 "$PROJ/assets/logo.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 256 256 "$PROJ/assets/logo.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 512 512 "$PROJ/assets/logo.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 1024 1024 "$PROJ/assets/logo.png" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$ICNS"
fi

rm -rf "$BUILD_DIR"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDisplayName</key><string>仿真模型生成</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>com.labtools.fangzhen-moxing-shengcheng</string>
  <key>CFBundleName</key><string>仿真模型生成</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launcher" << LAUNCH
#!/bin/bash
PROJ="$PROJ"
PY="/Users/yanghaoxiang/miniforge3/bin/python3"
[ -x "\$PY" ] || PY="\$(command -v python3)"
cd "\$PROJ" || exit 1
exec "\$PY" "\$PROJ/main.py" gui
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"

rm -rf "/Applications/$APP_NAME"
cp -R "$APP" "/Applications/$APP_NAME"
rm -rf "$HOME/Desktop/$APP_NAME"
cp -R "$APP" "$HOME/Desktop/$APP_NAME"
echo "Installed: /Applications/$APP_NAME and ~/Desktop/$APP_NAME"
