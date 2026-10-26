# Решения Android-клиента (feat/mobile-android)

Неясности задачи решаются осторожным вариантом; здесь — что выбрано и почему.

| № | решение | почему |
|---|---|---|
| D1 | `androidx.core:core` 1.18.0 (не 1.19.1) и OkHttp 5.3.2 (не 5.5.1) | 1.19.x и `okhttp-android` 5.5.x требуют compileSdk 37 (`checkAarMetadata`), а задача фиксирует compileSdk 36 |
| D2 | Тестовые зависимости сверх списка: Robolectric, `androidx.test:core`, OkHttp `mockwebserver3`, `org.json:json` | задача требует JUnit/Robolectric-тестов и мока на MockWebServer; `org.json` — настоящая реализация для чистых JVM-тестов (в android.jar только заглушки) |
| D3 | `lifecycle-livedata` и `lifecycle-viewmodel` входят в «lifecycle» из списка зависимостей | состояние экранов без своих Rx/корутин |
| D4 | Kotlin stdlib приходит транзитивно (OkHttp 5, androidx); прямых Kotlin-зависимостей и плагинов нет | разрешено задачей 0.1 |
| D5 | Gradle: `-Xmx1g -XX:+UseSerialGC` | на машине сборки мало commit-памяти: демон с 1,5–3 ГБ падал (hs_err: mmap failed) |
| D6 | Predictive back: `android:enableOnBackInvokedCallback="true"`; edge-to-edge — `EdgeToEdge.enable` + отступы по insets | targetSdk 36 |
