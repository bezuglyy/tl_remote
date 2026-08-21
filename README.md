# TL Remote

Кастомная интеграция [Home Assistant](https://www.home-assistant.io) для связывания двух инстансов HA: вы выбираете устройства на одном (узел), и они автоматически появляются на другом (приёмник).

![icon](custom_components/tl_remote/brand/icon.png)

## Зачем

У вас несколько Home Assistant (например, в разных сетях или на разном «железе»), и нужно видеть устройства одного из них в другом — но **не всё подряд**, а только то, что вы выбрали.

С `remote_homeassistant` выбор устройств делается на стороне *приёмника* (главного инстанса) — неудобно, если устройства логически принадлежат узлу. **TL Remote переворачивает сценарий:** устройства выбираются на стороне *узла* (где они физически живут), а приёмник просто зеркалит выбранное.

## Как это работает

```
┌──────────────────┐   WebSocket (WS API)   ┌──────────────────┐
│   УЗЕЛ (node)    │ ◄────────────────────► │ ПРИЁМНИК (main)  │
│  Белвью, 192.168.0.48 │                    │  База, 192.168.103.200 │
│                  │   REST discovery      │                  │
│  выбранные       │   (allowed entities)  │  зеркальные      │
│  сущности        │ ────────────────────► │  сущности        │
└──────────────────┘                       └──────────────────┘
```

1. **Узел** — инстанс, где живут устройства. В опциях интеграции вы отмечаете галочками сущности для экспорта. Узел отдаёт их список через endpoint `GET /api/tl_remote/discovery` (uuid, имя, версия, `allowed_entities`).
2. **Приёмник** — главный инстанс. Подключается к узлу по WebSocket, получает список разрешённых сущностей и зеркалит **только их**, создавая локальные сущности с опциональным префиксом (например, `belv_`).
3. Изменения на узле (отметили/сняли сущность) подхватываются приёмником в течение ~30 секунд.

## Возможности

- ✅ Выбор экспортируемых сущностей **на стороне узла** (мультиселект в UI)
- ✅ Зеркалирование любых доменов сущностей (sensor, button, media_player и т.д.)
- ✅ Опциональный префикс entity_id на приёмнике (например, `sensor.belv_aqara_...`)
- ✅ Живая синхронизация через WebSocket (`local_push`) + периодическая сверка списка
- ✅ Сенсор состояния соединения
- ✅ Иконка интеграции (HA 2026.3+) и иконки сущностей
- ✅ Переводы: русский, английский

## Установка

1. Скопируйте папку `custom_components/tl_remote/` в каталог `custom_components/` конфигурации **обоих** инстансов HA (узел и приёмник).
2. Перезапустите Home Assistant.
3. **На узле:** Настройки → Устройства и службы → Добавить интеграцию → **TL Remote** → роль **«Этот HA — источник устройств (узел)»**.
   Затем в карточке интеграции → **Параметры** → «Какие устройства отдавать» → отметьте нужные сущности.
4. **На приёмнике:** Настройки → Устройства и службы → Добавить интеграцию → **TL Remote** → роль **«Этот HA — приёмник»** → укажите адрес узла, порт (по умолчанию 8123) и **долгоживущий токен узла** (Профиль пользователя → Безопасность → Токены).
   В параметрах можно задать префикс сущностей (например, `belv`).

## Требования

- Home Assistant Core 2025.x и новее
- Интеграция ставится на **оба** инстанса

## Конфигурация

Интеграция настраивается полностью через UI (config flow + options flow). YAML-конфигурация не требуется.

## Структура

```
custom_components/tl_remote/
├── __init__.py      # логика: RemoteConnection (WebSocket, зеркалирование)
├── config_flow.py   # выбор роли (узел/приёмник), подключение, опции
├── const.py         # константы
├── icons.json       # иконки сущностей (MDI)
├── manifest.json    # манифест интеграции
├── sensor.py        # сенсор состояния соединения
├── views.py         # discovery endpoint узла
├── brand/           # иконка/логотип интеграции (HA 2026.3+)
└── translations/    # ru, en
```

## Лицензия

MIT

---

# TL Remote (English)

A custom integration for [Home Assistant](https://www.home-assistant.io) that links two HA instances: you select devices on one instance (the **node**), and they automatically appear on the other (the **main**).

## Why

You have several Home Assistant instances (e.g. in different networks or on different hardware) and you want to see devices from one of them in another — but **not everything**, only what you select.

With `remote_homeassistant` the entity selection happens on the *main* instance — inconvenient when devices logically belong to the node. **TL Remote flips the scenario:** devices are selected on the *node* (where they physically live), and the main instance simply mirrors what was selected.

## How it works

```
┌──────────────────┐   WebSocket (WS API)   ┌──────────────────┐
│   NODE           │ ◄────────────────────► │   MAIN           │
│  Belv, 192.168.0.48 │                    │  Baza, 192.168.103.200 │
│  selected        │   REST discovery      │  mirrored        │
│  entities        │ ────────────────────► │  entities        │
└──────────────────┘                       └──────────────────┘
```

1. **Node** — the instance where devices live. In the integration options you tick the entities to export. The node exposes them via `GET /api/tl_remote/discovery` (uuid, name, version, `allowed_entities`).
2. **Main** — the primary instance. It connects to the node over WebSocket, reads the allowed entity list and mirrors **only those**, creating local entities with an optional prefix (e.g. `belv_`).
3. Changes on the node (tick/untick an entity) are picked up by the main within ~30 seconds.

## Features

- ✅ Entity selection **on the node side** (multi-select UI)
- ✅ Mirroring of any entity domain (sensor, button, media_player, ...)
- ✅ Optional entity_id prefix on the main (e.g. `sensor.belv_aqara_...`)
- ✅ Live WebSocket sync (`local_push`) + periodic list re-check
- ✅ Connection status sensor
- ✅ Integration icon (HA 2026.3+) and entity icons
- ✅ Translations: English, Russian

## Installation

1. Copy the `custom_components/tl_remote/` folder into the `custom_components/` directory of **both** HA instances (node and main).
2. Restart Home Assistant.
3. **On the node:** Settings → Devices & Services → Add Integration → **TL Remote** → role **"This HA exposes devices (node)"**. Then open the integration → **Options** → "Which devices to expose" and tick the entities.
4. **On the main:** Settings → Devices & Services → Add Integration → **TL Remote** → role **"This HA connects to another HA (main)"** → enter the node address, port (default 8123) and a **long-lived access token** of the node (Profile → Security → Tokens). You can set an entity prefix (e.g. `belv`) in the options.

## Requirements

- Home Assistant Core 2025.x and newer
- The integration must be installed on **both** instances

## License

MIT
