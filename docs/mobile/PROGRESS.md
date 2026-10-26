# Прогресс разработки мобильного клиента Sakura (Android)

## Задача 0: Проверка окружения и каркаса Android

- **Git**: `git version 2.55.0.windows.5`, origin = `https://github.com/quandrant22/sakura.git`, ветка `feat/mobile-android` (база `origin/master`, commit `8dc9e6cea188643c058a8a808449b33f7f129255`).
- **JDK**: OpenJDK 21.0.10 (JBR Android Studio: `C:\Program Files\Android\Android Studio\jbr`).
- **Gradle**: 9.4.1
- **AGP**: 9.2.1
- **Android SDK**: `C:\Users\MosTech\AppData\Local\Android\Sdk`
- **Установленные пакеты SDK**: `platforms;android-36`, `build-tools;36.0.0` (автоматически загружены и лицензии приняты AGP/Gradle), а также `android-36.1`, `36.1.0`, `37.0.0`. `cmdline-tools` отсутствует в дистрибутиве SDK (владельцу при необходимости установит SDK Manager в Studio).
- **Серверная часть**: передана отдельному агенту.
- **Результат сборки каркаса**: `gradlew.bat assembleDebug testDebugUnitTest` — SUCCESSFUL (38 задач выполнено, unit-тесты пройдены).
- **Коммит каркаса**: `4ee83dbc7cdcf543483589cd63ecb169504fdc7c` (`chore(mobile): каркас Android-проекта (Java, Views, minSdk 33, Groovy DSL, SDK 36)`).

## Задача 0.1: исправления каркаса

- Бэкап запрещён: `allowBackup="false"`, `fullBackupContent` и `backup_rules.xml` удалены; `data_extraction_rules.xml` исключает root/file/database/sharedpref/external для cloud-backup и device-transfer.
- Release: `minifyEnabled true` + `shrinkResources true` (R8, обфускация), правила в `app/proguard-rules.pro`; `Log.d`/`Log.v` вырезаются через `-assumenosideeffects`. Новый DSL `optimization.enable` в AGP 9.2.1 требует экспериментального флага `android.r8.gradual.support`, поэтому взят классический.
- Зависимости: `activity-ktx` → `androidx.activity:activity` 1.13.0; appcompat 1.8.0, material 1.14.0, constraintlayout 2.2.2, junit 4.13.2, ext-junit 1.3.0, espresso 3.7.0. Прямых Kotlin-зависимостей и плагинов нет.
- `gradlew.bat clean assembleDebug assembleRelease testDebugUnitTest` — BUILD SUCCESSFUL (82 задачи); release проверен с временной подписью debug-ключом, в git её нет. JDK — Android Studio JBR (`JAVA_HOME` не задан в системе).

## Уборка (задача 0.2)

- Каталог `mobile/android/memory/` удалён, не открывая файлы. Причина появления: модули сервера пишут в относительные пути (`config.py`: `KEYS_FILE = "memory/api_keys.json"`; `modules/relationship.py`: `memory/first_run.json`; `modules/fortune_cookie.py` и др.), а серверный код запускался (pytest в задаче 0) с рабочим каталогом сессии `mobile/android`. Файлы созданы 26.10 12:48–12:58. Защита: `memory/` в `mobile/android/.gitignore`; серверный код из `mobile/android` больше не запускается.
