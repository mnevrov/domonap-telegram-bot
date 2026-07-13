Java.perform(function() {
    var TARGET_KEYS = [
        "prefs_key_access_token",
        "prefs_key_refresh_token",
        "LOCAL_DATA_COMPLETE_TOKEN"
    ];

    function isTarget(key) {
        return TARGET_KEYS.indexOf(key) >= 0;
    }

    // Hook 1: TokenDataSourceImpl.saveTokens(access, refresh)
    try {
        var TokenDataSource = Java.use("com.domonap.sdk.auth.data.source.TokenDataSourceImpl");
        TokenDataSource.saveTokens.implementation = function(accessToken, refreshToken) {
            console.log("[TOKEN] access_token=" + accessToken);
            console.log("[TOKEN] refresh_token=" + refreshToken);
            return this.saveTokens(accessToken, refreshToken);
        };
        console.log("[FRIDA] Hooked TokenDataSourceImpl.saveTokens");
    } catch (e) {
        console.log("[FRIDA] TokenDataSourceImpl not found: " + e);
    }

    // Hook 2: SharedPreferences.Editor.putString — catches all writes
    try {
        var Editor = Java.use("android.app.SharedPreferencesImpl$EditorImpl");
        Editor.putString.implementation = function(key, value) {
            if (isTarget(key)) {
                console.log("[PREFS_PUT] " + key + "=" + value);
            }
            return this.putString(key, value);
        };
        console.log("[FRIDA] Hooked EditorImpl.putString");
    } catch (e) {
        console.log("[FRIDA] EditorImpl not found: " + e);
    }

    // Hook 3: SharedPreferences.getString — catches reads (existing tokens)
    try {
        var SharedPreferences = Java.use("android.app.SharedPreferencesImpl");
        SharedPreferences.getString.implementation = function(key, defValue) {
            var result = this.getString(key, defValue);
            if (isTarget(key)) {
                console.log("[PREFS_GET] " + key + "=" + result);
            }
            return result;
        };
        console.log("[FRIDA] Hooked SharedPreferencesImpl.getString");
    } catch (e) {
        console.log("[FRIDA] SharedPreferencesImpl not found: " + e);
    }

    console.log("[FRIDA] All hooks installed. Open the app or trigger login.");
});
