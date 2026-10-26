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
# Отладочные логи вырезаются из release.
-assumenosideeffects class android.util.Log {
    public static int d(...);
    public static int v(...);
}
