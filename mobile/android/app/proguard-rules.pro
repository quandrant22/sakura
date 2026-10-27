# Add project specific R8 rules here.
# Подключён в app/build.gradle (release).
#
# For more details, see
#   https://d.android.com/r/tools/r8/keep-rules

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}
# Vosk работает через JNA: нативный код ищет классы и поля по именам.
-keep class com.sun.jna.** { *; }
-keep class * implements com.sun.jna.** { *; }
-keep class org.vosk.** { *; }
-dontwarn java.awt.**
-dontwarn com.sun.jna.**

# Отладочные логи вырезаются из release.
-assumenosideeffects class android.util.Log {
    public static int d(...);
    public static int v(...);
}
