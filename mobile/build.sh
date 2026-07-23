#!/usr/bin/env bash

# Exit immediately if any command fails
set -e

echo "🚀 Starting APK Build Process..."

# 1. Set environment variables for Java 21
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH

# 2. Mirror the SAFi web app into the Capacitor webDir so mobile always
#    ships whatever is currently in ../public — never a hand-copied snapshot.
echo "📦 Syncing web assets from ../public..."
rsync -a --delete \
  --exclude='package.json' \
  --exclude='package-lock.json' \
  --exclude='tailwind.config.js' \
  ../public/ chat/

# 3. Sync web assets and native plugins to Capacitor
echo "🔄 Syncing Capacitor Android assets..."
npx cap sync android

# 4. Navigate to the android directory and build the APK
echo "⚙️ Compiling Debug APK with Gradle..."
cd android
chmod +x gradlew
./gradlew assembleDebug

# 5. Output location
cd ..
APK_PATH="android/app/build/outputs/apk/debug/app-debug.apk"

echo ""
echo "✅ Build Complete!"
echo "📍 APK Location: $(pwd)/$APK_PATH"
