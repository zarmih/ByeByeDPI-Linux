[![CI](https://github.com/zarmih/ByeByeDPI-Linux/actions/workflows/ci.yml/badge.svg)](https://github.com/zarmih/ByeByeDPI-Linux/actions/workflows/ci.yml)

# ByeByeDPI Linux

Это графический интерфейс (GUI) для [ByeDPI (ciadpi)](https://github.com/hufrea/byedpi), инструмента обхода DPI в Linux.
Проект является настольным Linux-клиентом без прав `root` (`sudo`). Он не изменяет маршруты, firewall, DNS или NetworkManager. Основной режим — локальный SOCKS5-прокси; дополнительная интеграция GNOME использует только пользовательские настройки `gsettings`.

**Ограничения (Важно!)**
*   Это **НЕ** полноценный VPN.
*   Ваш реальный IP-адрес **НЕ** скрывается от посещаемых сайтов.
*   Это не прозрачный TUN/VPN: приложения, игнорирующие системные proxy-настройки, не будут автоматически направлены через ByeDPI.
*   Надёжный универсальный вариант — вручную указать SOCKS5 `127.0.0.1:1080` в нужном приложении. В GNOME можно опционально включить системную SOCKS-настройку; предыдущие значения сохраняются в аварийном журнале и восстанавливаются при Stop/Quit или следующем запуске.

## Установка и запуск

### Пользовательская установка без root

```bash
git clone --recurse-submodules https://github.com/zarmih/ByeByeDPI-Linux.git
cd ByeByeDPI-Linux
./scripts/install-user.sh
```

Установщик проверит Python 3.10+, `venv`, `make` и C-компилятор, при необходимости соберёт `ciadpi`, создаст изолированное окружение (с ускорением через `uv` при наличии, иначе fallback на `pip`) и установит launcher/desktop-файл в `~/.local`. Предварительный план без изменений:

```bash
./scripts/install-user.sh --dry-run
```

Удаление: `./scripts/uninstall-user.sh`. История и настройки сохраняются; для их удаления используйте `--purge-data`.

### Запуск из исходников

```bash
make -C vendor/byedpi
./bootstrap
./dev-run
```
   *Скрипт `dev-run` автоматически выберет доступный графический frontend. **PySide6 (Qt)** является основным и приоритетным фронтендом (версия 6.11.1 успешно протестирована). Если он недоступен, будет использован нативный **GTK3 (PyGObject)** через системный Python. Если и GTK3 отсутствует, запустится минималистичный fallback **Tkinter**.*

## Features

- **Profile Management**: Pre-configured profiles (Default, Fake, Split) and a Custom profile option.
- **Persistence**: Remembers your selected profile, custom arguments, and window geometry.
- **System Integration**:
  - Minimize to system tray when a tray service is available; otherwise window close performs full cleanup.
  - Automatically manages the `ciadpi` process and restores a pending GNOME proxy journal on startup/Stop/Quit.
  - *Optional* user-level GNOME SOCKS proxy configuration via `gsettings`. It is not VPN/TUN and may be ignored by some applications.
- **Diagnostics**: Built-in first-run readiness and diagnostics tool. It safely checks the presence of `ciadpi` binary, PySide6 version, `curl`, writable directories, and local port availability. The diagnostics module operates strictly read-only and offline: it does NOT modify system settings, does NOT send any network requests, and redacts personal paths from the exported reports (JSON/TXT).
- **Result History & Comparison**: Save test results, export to CSV, and visually compare performance and capabilities between different DPI bypass strategies.
- **User Installation**: Easy `install-user.sh` for non-root installation to `~/.local`.



## Релизы, CI и лицензия

Текущая версия приложения: **0.3.0**. GitHub Actions собирает `ciadpi`, запускает полный pytest и Qt-smoke на Python 3.10/3.12, затем создаёт воспроизводимый source-архив как workflow artifact.

Локальная сборка такого же архива:

```bash
scripts/build-release.sh --output-dir dist
sha256sum -c dist/ByeByeDPI-Linux-0.3.0.tar.gz.sha256
```

Архив включает исходники закреплённого submodule ByeDPI, внутренний `SHA256SUMS`, metadata и лицензии, но не включает локально собранный бинарник `ciadpi`. Подробности: [`docs/RELEASING.md`](docs/RELEASING.md) и [`CHANGELOG.md`](CHANGELOG.md).

ByeByeDPI-Linux распространяется по **GPL-3.0-only**. Сторонние компоненты и их условия перечислены в [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); `vendor/byedpi` сохраняет MIT-лицензию upstream.

## Безопасное обновление данных

Update Center работает в два этапа: **Preview** и явный **Apply**. Preview фиксирует полный 40-символьный SHA официального Android-репозитория, загружает ограниченный объём UTF-8 данных, нормализует IDN-домены, проверяет уникальность ID/групп/целей и вычисляет content-diff без учёта служебных метаданных. Прокси обновления принимает только URL вида `http://host:port` или `https://host:port`; credentials в URL запрещены и не сохраняются.

Backup хранится вне репозитория в пользовательском data-каталоге. Apply и Rollback используют временный файл, `fsync` и `os.replace`; после записи JSON повторно читается и проверяется. Хранятся последние 10 резервных копий каждого типа.

## Безопасность и границы интеграции

Подробная модель угроз, аварийное восстановление GNOME proxy и ограничения режима SOCKS описаны в [`docs/SECURITY.md`](docs/SECURITY.md).

## Библиотека Стратегий и Тестирование

  Для обеспечения наилучшего обхода блокировок в `PySide6` (основном интерфейсе) реализована **Библиотека стратегий**. Тестировщик работает матрично: каждая из стратегий тестируется на выбранных пользователем целевых сайтах.

  - **Источник стратегий и сайтов:** Официальный Android-клиент [romanvht/ByeByeDPI](https://github.com/romanvht/ByeByeDPI).
  - **Количество стратегий:** 60 шт. (файл `proxytest_strategies.list`). Их параметры синтаксически совместимы с закреплённой версией `ciadpi`; фактическая эффективность зависит от провайдера и сети.
  - **Тестовые сайты (Targets):** 139 сайтов, разбитых на 8 групп (файлы `proxytest_*.sites` в `app/src/main/assets/`). Группы по умолчанию (Default): YouTube и GoogleVideo. Пользователь может выбрать любые встроенные группы или импортировать свой JSON-список.
  - **Upstream commit:** `ffda4fa93d94472217c75e51b45fdd18f966c0af`.

  **Как работает тестирование:**
  В окне *Library* выберите нужные группы/сайты в левом дереве. Затем нажмите **Test All** (для прогона всех стратегий) или **Test Selected** (для конкретной).
  1. Для каждой тестируемой стратегии запускается один процесс `ciadpi` с локальным SOCKS5-прокси на случайном порту.
  2. Через этот прокси делаются HTTPS-запросы ко всем выбранным сайтам (метод GET, без загрузки тела, с проверкой соединения и обработкой редиректов, согласно логике Android). Успехом (network success) считается любой HTTP-код (даже 403 или 500), если `curl` завершился с кодом 0.
  3. В таблице отображается агрегированный результат: сколько сайтов открылось, процент успеха, среднее и медианное время ответа, количество таймаутов/ошибок, а также глобальный прогресс тестирования и ETA (приблизительная оценка оставшегося времени).
  4. Двойной клик по стратегии покажет **Details Dialog** с детальными результатами по каждому сайту, агрегацией по группам, и фильтрами (Status, Search) для удобного анализа.
  5. По завершении теста вы можете нажать **Select Best**, чтобы выбрать стратегию по единому критерию: Passed (DESC) -> Success Rate (DESC) -> Median Time (ASC) -> Errors (ASC).
  6. Доступна пауза/возобновление (Pause/Resume) долгих тестов (пауза применяется между отдельными запросами к целевым сайтам) и полный экспорт/импорт результатов тестирования в JSON/CSV без необходимости повторного прогона.

  > **Важно:** Успешный HTTPS-тест в библиотеке лишь проверяет факт прохождения TLS-соединения (отсутствие RST от провайдера). Это **не гарантирует**, что этот метод надёжно обойдёт все DPI-блокировки в вашем браузере. Результаты сильно зависят от вашего провайдера. Помните, что это не VPN — ваш реальный IP-адрес не скрывается от конечного сервера!

  - **Центр обновлений:** в окне **Library** нажмите **Updates…**. Программа сначала получает полный upstream SHA, скачивает assets именно из этой ревизии, проверяет схему/лимиты и показывает Added/Removed/Changed. Кнопка Apply доступна только после Preview; перед атомарной заменой создаётся резервная копия, которую можно выбрать и восстановить через Rollback. Полученные аргументы никогда не запускаются автоматически.
  - **CLI:** те же проверки доступны через `scripts/update_strategies.py` и `scripts/update_test_targets.py`. Используйте `--dry-run`, при необходимости `--proxy http://127.0.0.1:10808`; `--rollback` восстанавливает последнюю резервную копию.

  > **Внимание:** Fallback-интерфейсы (GTK3 и Tkinter) предоставляют базовый функционал запуска и не содержат графической библиотеки стратегий. Для полного функционала используйте PySide6.

  ## Настройка браузера (на примере Firefox)

Поскольку программа работает как SOCKS5-прокси, вам нужно направить трафик браузера через неё:
1. Откройте **Настройки (Settings)** в Firefox.
2. Прокрутите в самый низ до **Параметры сети (Network Settings)** и нажмите **Настроить (Settings...)**.
3. Выберите **Ручная настройка прокси (Manual proxy configuration)**.
4. В поле **Хост SOCKS (SOCKS Host)** введите `127.0.0.1`, а в поле **Порт (Port)** — `1080` (или другой, если вы изменили его в аргументах).
5. Убедитесь, что выбран **SOCKS v5**.
6. **ОБЯЗАТЕЛЬНО** поставьте галочку **Использовать прокси DNS при использовании SOCKS v5 (Proxy DNS when using SOCKS v5)**.
7. Нажмите ОК.

*Чтобы вернуть настройки обратно, выберите "Без прокси" (No proxy).*
## Разработка и тестирование

Для запуска тестов выполните:
```bash
source .venv/bin/activate
pytest tests/
```

### Сохранение и история результатов (Schema v2)
Формат экспорта тестов был обновлен до **Schema v2**. Теперь каждый экспортируемый файл самодостаточен и содержит полные метаданные (версия, даты, статусы), использовавшиеся профили стратегий и целей, а также результаты с агрегированной статистикой. Импорт старых файлов (Schema v1) поддерживается: при загрузке они будут безопасно мигрированы в новый формат.
* **Локальная история прогонов**: последние 20 запусков тестов сохраняются автоматически (по умолчанию включена галочка **Auto-save History**). Выбор запоминается через `QSettings`; автосохранение можно отключить. Нажмите кнопку **History** в окне библиотеки, чтобы открыть историю.
* **Приватность**: история хранится **исключительно локально** и никуда не отправляется. В Linux каталог: `~/.local/share/ByeByeDPI-Linux/history` (или `$XDG_DATA_HOME/ByeByeDPI-Linux/history`, определяется через `QStandardPaths.GenericDataLocation`).
* **Управление**: Вы можете открыть любой старый прогон, удалить его или полностью очистить историю (кнопка `Clear History`).
* **Сравнение прогонов (Compare)**: В окне истории можно выбрать ровно 2 прогона и нажать `Compare`, чтобы увидеть разницу в проценте успешных запросов, изменениях времени ответа и изменении рейтинга каждой стратегии.
* **Экспорт**: Доступен экспорт истории в виде JSON (Schema v2), Flat CSV (все запросы) и Summary CSV (агрегированная таблица стратегий).

> **Ограничение**: Импорт JSON проверяет целостность и пересчитывает статистику на лету, поэтому он полностью безопасен. Секретные данные (если они случайно попали в память) удаляются перед сохранением.
