import type { CapacitorConfig } from '@capacitor/cli';

/**
 * This is your WEB Client ID.
 * It matches what is in your app.js and auth.py.
 * Used for the 'serverClientId' to get the auth code.
 */
const WEB_CLIENT_ID = '391499357887-ggqkfpcqptcr93raffcv5mhgufmlu92v.apps.googleusercontent.com';

/**
 * This is your ANDROID Client ID.
 * CRITICAL: This must be the Client ID type "Android" from Google Cloud Console
 * that matches your app's package name (com.safi.app) and SHA-1 fingerprint.
 * It is DIFFERENT from the Web Client ID.
 */
const ANDROID_CLIENT_ID = '391499357887-1mvm6ar9rua970i0p3cl6hd1r7vt1qvp.apps.googleusercontent.com'; 

const config: CapacitorConfig = {
  appId: 'com.safi.app',
  appName: 'SAFi',
  /**
   * CHANGED: 'public' matches the folder name in your __init__.py.
   * Your Flask app serves static files from '../public'.
   */
  webDir: 'chat', 
  server: {
    androidScheme: 'https',
    hostname: 'selfalignmentframework.com',
    // Ensure cleartext traffic is allowed if testing locally, 
    // but for production hostname 'https' is fine.
    cleartext: true,
    // FIX: Explicitly allow navigation to Microsoft domains.
    // This ensures the redirect happens inside the app/webview smoothly.
    allowNavigation: [
      "*.google.com",
      "*.googleapis.com",
      "*.microsoft.com",
      "*.microsoftonline.com",
      "*.live.com",
      "graph.microsoft.com",
      "selfalignmentframework.com"
    ]
  },
  // FIX: "Bad Formatting" on Microsoft Login
  // We must append a standard Chrome User Agent string.
  // Without this, Microsoft sees "WebView" and serves a broken legacy mobile page.
  android: {
    appendUserAgent: "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
  },
  plugins: {
    GoogleAuth: {
      scopes: ['profile', 'email'],
      
      // The Web Client ID (Request this code to send to backend)
      serverClientId: WEB_CLIENT_ID,

      // The Android Client ID (Used by the device to authorize the app)
      androidClientId: ANDROID_CLIENT_ID,

      // Fallback ID
      clientId: WEB_CLIENT_ID,

      // Critical for the 'code' flow we are using in auth.py
      forceCodeForRefreshToken: true
    },
    SplashScreen: {
      launchShowDuration: 3000,
      launchAutoHide: true,
      backgroundColor: "#ffffff"
    }
  }
};

export default config;