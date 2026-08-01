# ProЗапас — техническое задание на базу данных

Схема PostgreSQL для складской системы. Работает в паре с
[backend-spec.md](backend-spec.md); архитектурные обоснования —
[architecture.md](architecture.md).

---

## 1. Общие соглашения

| | |
|---|---|
| СУБД | PostgreSQL 16 |
| Кодировка | UTF-8, collation `ru_RU.UTF-8` |
| Часовой пояс | всё в UTC, тип `timestamptz` |
| Именование | таблицы в единственном числе (`order`, `stock_balance`), поля `snake_case` |
| Первичные ключи | `id bigserial`, кроме таблиц связей |
| Внешние ключи | `<таблица>_id`, всегда с явным `ON DELETE` |
| Миграции | Alembic, схема не правится руками ни на одном стенде |

Зарезервированные слова экранируются: таблица заказов называется `"order"`,
поэтому в коде используется алиас `orders_table`.

Служебные поля у всех таблиц:

```sql
created_at  timestamptz NOT NULL DEFAULT now()
updated_at  timestamptz NOT NULL DEFAULT now()   -- обновляется триггером
```

## 2. Перечисления

Реализуются как `CHECK`-ограничения по текстовому полю, а не как `ENUM`-типы:
добавить значение в `CHECK` проще, чем менять тип в PostgreSQL.

| Поле | Значения |
|---|---|
| `order.direction` | `ours`, `theirs` |
| `order.status` | `created`, `processing`, `shipped`, `received`, `declined`, `cancelled` |
| `shipment.status` | `waiting`, `progress`, `done` |
| `receipt_batch.status` | `waiting`, `progress`, `done` |
| `stock_movement.type` | `receipt`, `shipment`, `writeoff`, `recount`, `reserve`, `unreserve` |
| `user_account.status` | `active`, `blocked` |
| `role.code` | `manager`, `stockman`, `admin` |
| `role_permission.section` | `orders`, `shipping`, `receiving`, `catalog`, `stock`, `users` |
| `print_job.status` | `queued`, `printing`, `done`, `failed` |

## 3. Схема

### 3.1 Справочники

```sql
CREATE TABLE warehouse (
    id                   bigserial PRIMARY KEY,
    code                 text NOT NULL UNIQUE,          -- «128», идёт в штрихкод
    name                 text NOT NULL UNIQUE,          -- «Центральный склад»
    responsible_user_id  bigint REFERENCES user_account(id) ON DELETE SET NULL,
    is_own               boolean NOT NULL DEFAULT false, -- наш склад или контрагент
    is_active            boolean NOT NULL DEFAULT true,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE supplier (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    inn         text,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog_item (
    id           bigserial PRIMARY KEY,
    article      text NOT NULL UNIQUE,                  -- «100421», внутренний
    code1c       text UNIQUE,                           -- «ТМЦ-00421», ключ обмена с 1С
    name         text NOT NULL,
    unit         text NOT NULL,                         -- шт., м, лист
    unit_weight  numeric(10,3) NOT NULL DEFAULT 0 CHECK (unit_weight >= 0),
    is_archived  boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX catalog_item_search_idx ON catalog_item
    USING gin (to_tsvector('russian', name || ' ' || article || ' ' || coalesce(code1c, '')));
CREATE INDEX catalog_item_active_idx ON catalog_item (is_archived) WHERE NOT is_archived;
```

Позиция никогда не удаляется физически — только `is_archived`, потому что она
фигурирует в истории движений и в закрытых заказах.

### 3.2 Учётные записи и права

```sql
CREATE TABLE role (
    id     bigserial PRIMARY KEY,
    code   text NOT NULL UNIQUE CHECK (code IN ('manager','stockman','admin')),
    label  text NOT NULL
);

CREATE TABLE user_account (
    id             bigserial PRIMARY KEY,
    full_name      text NOT NULL,
    email          text NOT NULL UNIQUE,
    password_hash  text NOT NULL,                       -- argon2id
    role_id        bigint NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    warehouse_id   bigint REFERENCES warehouse(id) ON DELETE SET NULL,
    position       text,
    phone          text,
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','blocked')),
    hire_date      date,
    last_login_at  timestamptz,
    deleted_at     timestamptz,                          -- мягкое удаление
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX user_account_email_idx ON user_account (lower(email))
    WHERE deleted_at IS NULL;
CREATE INDEX user_account_role_idx ON user_account (role_id) WHERE deleted_at IS NULL;

CREATE TABLE role_permission (
    role_id   bigint NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    section   text NOT NULL CHECK (section IN
                 ('orders','shipping','receiving','catalog','stock','users')),
    can_view  boolean NOT NULL DEFAULT false,
    can_edit  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (role_id, section),
    CHECK (can_view OR NOT can_edit)                     -- редактировать, не видя, нельзя
);

CREATE TABLE refresh_token (
    id          bigserial PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,                    -- сам токен не хранится
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX refresh_token_user_idx ON refresh_token (user_id) WHERE revoked_at IS NULL;
```

Пользователь удаляется мягко: он остаётся автором заказов и движений.

### 3.3 Остатки и движения

```sql
CREATE TABLE stock_balance (
    item_id       bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    warehouse_id  bigint NOT NULL REFERENCES warehouse(id) ON DELETE RESTRICT,
    qty           integer NOT NULL DEFAULT 0 CHECK (qty >= 0),
    reserved      integer NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    min_qty       integer NOT NULL DEFAULT 0 CHECK (min_qty >= 0),
    version       integer NOT NULL DEFAULT 1,            -- оптимистичная блокировка
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, warehouse_id),
    CHECK (reserved <= qty)
);

CREATE INDEX stock_balance_warehouse_idx ON stock_balance (warehouse_id);
CREATE INDEX stock_balance_below_min_idx ON stock_balance (item_id)
    WHERE qty - reserved < min_qty;

CREATE TABLE stock_movement (
    id            bigserial PRIMARY KEY,
    item_id       bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    warehouse_id  bigint NOT NULL REFERENCES warehouse(id) ON DELETE RESTRICT,
    type          text NOT NULL CHECK (type IN
                    ('receipt','shipment','writeoff','recount','reserve','unreserve')),
    delta         integer NOT NULL,                      -- со знаком
    balance_after integer NOT NULL,                      -- остаток после операции
    doc_type      text,                                  -- order · shipment · receipt · manual
    doc_id        bigint,
    comment       text,
    user_id       bigint REFERENCES user_account(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX stock_movement_item_idx ON stock_movement (item_id, created_at DESC);
CREATE INDEX stock_movement_doc_idx ON stock_movement (doc_type, doc_id);
```

`stock_movement` — журнал только на добавление: записи не изменяются и не
удаляются. `balance_after` хранится намеренно, чтобы карточка товара не
пересчитывала историю на каждом открытии.

**Инвариант:** для любой пары «позиция + склад» сумма `delta` по движениям типов
`receipt`, `shipment`, `writeoff`, `recount` равна `stock_balance.qty`. Проверяется
регулярным тестом и сверочным запросом (раздел 8).

### 3.4 Заказы

```sql
CREATE TABLE "order" (
    id                        bigserial PRIMARY KEY,
    number                    text NOT NULL UNIQUE,
    direction                 text NOT NULL CHECK (direction IN ('ours','theirs')),
    status                    text NOT NULL CHECK (status IN
                                ('created','processing','shipped','received',
                                 'declined','cancelled')),
    counterparty_warehouse_id bigint NOT NULL REFERENCES warehouse(id) ON DELETE RESTRICT,
    responsible_user_id       bigint REFERENCES user_account(id) ON DELETE SET NULL,
    comment                   text,
    decline_reason            text,
    cancel_reason             text,
    shipped_at                timestamptz,
    accepted_at               timestamptz,
    version                   integer NOT NULL DEFAULT 1,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX order_list_idx ON "order" (direction, status, created_at DESC);
CREATE INDEX order_warehouse_idx ON "order" (counterparty_warehouse_id);
CREATE INDEX order_number_idx ON "order" (number text_pattern_ops);

CREATE TABLE order_position (
    id        bigserial PRIMARY KEY,
    order_id  bigint NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    item_id   bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    qty       integer NOT NULL CHECK (qty > 0),
    UNIQUE (order_id, item_id)                           -- позиция в заказе одна
);

CREATE INDEX order_position_order_idx ON order_position (order_id);

CREATE TABLE order_status_event (
    id          bigserial PRIMARY KEY,
    order_id    bigint NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    status      text NOT NULL,
    reason      text,
    user_id     bigint REFERENCES user_account(id) ON DELETE SET NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX order_status_event_order_idx ON order_status_event (order_id, occurred_at);

CREATE SEQUENCE order_number_ours_seq   START 2001;
CREATE SEQUENCE order_number_theirs_seq START 3001;
```

Позиция хранит только `item_id` и `qty`; наименование, единица и вес берутся из
справочника. Это то же правило, что уже действует в JSON-файле приложения.

### 3.5 Отгрузка

```sql
CREATE TABLE shipment (
    id                   bigserial PRIMARY KEY,
    order_id             bigint NOT NULL UNIQUE REFERENCES "order"(id) ON DELETE CASCADE,
    status               text NOT NULL DEFAULT 'waiting'
                           CHECK (status IN ('waiting','progress','done')),
    responsible_user_id  bigint REFERENCES user_account(id) ON DELETE SET NULL,
    shipped_at           timestamptz,
    version              integer NOT NULL DEFAULT 1,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shipment_box (
    id            bigserial PRIMARY KEY,
    shipment_id   bigint NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
    barcode       text NOT NULL UNIQUE,
    item_id       bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    qty           integer NOT NULL CHECK (qty > 0),
    weight        numeric(10,3) NOT NULL CHECK (weight > 0),
    printed_at    timestamptz,
    user_id       bigint REFERENCES user_account(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX shipment_box_shipment_idx ON shipment_box (shipment_id);
CREATE INDEX shipment_box_item_idx ON shipment_box (item_id);
```

**Инвариант:** сумма `qty` коробок по позиции не превышает `order_position.qty`.
Проверяется в сервисном слое внутри транзакции (выразить это `CHECK`-ом нельзя).

### 3.6 Приёмка

```sql
CREATE TABLE receipt_batch (
    id                   bigserial PRIMARY KEY,
    number               text NOT NULL UNIQUE,
    supplier_id          bigint REFERENCES supplier(id) ON DELETE RESTRICT,
    order_id             bigint UNIQUE REFERENCES "order"(id) ON DELETE SET NULL,
    status               text NOT NULL DEFAULT 'waiting'
                           CHECK (status IN ('waiting','progress','done')),
    warehouse_id         bigint NOT NULL REFERENCES warehouse(id) ON DELETE RESTRICT,
    responsible_user_id  bigint REFERENCES user_account(id) ON DELETE SET NULL,
    ship_at              timestamptz,
    accepted_at          timestamptz,
    version              integer NOT NULL DEFAULT 1,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (supplier_id IS NOT NULL OR order_id IS NOT NULL)
);

CREATE INDEX receipt_batch_list_idx ON receipt_batch (status, created_at DESC);

CREATE TABLE receipt_batch_position (
    id          bigserial PRIMARY KEY,
    batch_id    bigint NOT NULL REFERENCES receipt_batch(id) ON DELETE CASCADE,
    item_id     bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    boxes       integer NOT NULL CHECK (boxes > 0),
    box_weight  numeric(10,3) NOT NULL CHECK (box_weight > 0),
    UNIQUE (batch_id, item_id)
);

CREATE TABLE receipt_scan (
    id              bigserial PRIMARY KEY,
    batch_id        bigint NOT NULL REFERENCES receipt_batch(id) ON DELETE CASCADE,
    barcode         text NOT NULL,
    item_id         bigint NOT NULL REFERENCES catalog_item(id) ON DELETE RESTRICT,
    expected_weight numeric(10,3) NOT NULL,
    actual_weight   numeric(10,3),                       -- NULL, если коробка не пришла
    diff_kg         numeric(10,3),
    diff_percent    numeric(6,2),
    is_missing      boolean NOT NULL DEFAULT false,
    user_id         bigint REFERENCES user_account(id) ON DELETE SET NULL,
    scanned_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_id, barcode)                           -- коробку не принять дважды
);

CREATE INDEX receipt_scan_batch_idx ON receipt_scan (batch_id);
```

Ожидаемые коробки не материализуются: они разворачиваются из
`receipt_batch_position` (`boxes` штук на позицию) и сравниваются с уже
отсканированными. Хранить их отдельной таблицей незачем — состав партии не
меняется.

### 3.7 Этикетки и печать

```sql
CREATE TABLE label_template (
    id         bigserial PRIMARY KEY,
    code       text NOT NULL UNIQUE,                     -- box · item
    format     text NOT NULL CHECK (format IN ('zpl','tspl')),
    width_mm   integer NOT NULL,
    height_mm  integer NOT NULL,
    dpi        integer NOT NULL DEFAULT 203,
    body       text NOT NULL,                            -- шаблон с подстановками
    version    integer NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE print_job (
    id               bigserial PRIMARY KEY,
    barcode          text NOT NULL,
    template_id      bigint REFERENCES label_template(id) ON DELETE SET NULL,
    template_version integer,
    is_reprint       boolean NOT NULL DEFAULT false,
    status           text NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued','printing','done','failed')),
    error            text,
    user_id          bigint REFERENCES user_account(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX print_job_barcode_idx ON print_job (barcode, created_at DESC);
```

Макет хранится в базе, чтобы его смена не требовала обновления приложений на
рабочих местах. `template_version` фиксирует, каким макетом печаталась конкретная
этикетка.

### 3.8 Служебные таблицы

```sql
CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    entity      text NOT NULL,                           -- order · user_account · …
    entity_id   bigint NOT NULL,
    action      text NOT NULL,                           -- create · update · delete · transition
    before      jsonb,
    after       jsonb,
    user_id     bigint REFERENCES user_account(id) ON DELETE SET NULL,
    request_id  text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_entity_idx ON audit_log (entity, entity_id, created_at DESC);
CREATE INDEX audit_log_user_idx ON audit_log (user_id, created_at DESC);

CREATE TABLE idempotency_key (
    key           text PRIMARY KEY,
    request_hash  text NOT NULL,                         -- хеш тела запроса
    response      jsonb NOT NULL,
    status_code   integer NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idempotency_key_created_idx ON idempotency_key (created_at);
```

Ключи идемпотентности старше 24 часов удаляются регламентным заданием.

## 4. Связи

```
role ──< user_account >── warehouse
  └──< role_permission

catalog_item ──< stock_balance >── warehouse
      │              │
      └──< stock_movement >───────┘

warehouse ──< "order" ──< order_position >── catalog_item
                 │  └──< order_status_event
                 ├──── shipment ──< shipment_box >── catalog_item
                 └──── receipt_batch ──< receipt_batch_position >── catalog_item
                              │        └──< receipt_scan
                              └── supplier

label_template ──< print_job
```

## 5. Инварианты

Часть выражена ограничениями, часть проверяется в сервисном слое внутри
транзакции — там, где `CHECK` бессилен.

| Инвариант | Где проверяется |
|---|---|
| `reserved <= qty`, обе величины неотрицательны | `CHECK` в `stock_balance` |
| Списание не уходит в минус | `UPDATE … WHERE qty - reserved >= :n` |
| Сумма движений равна балансу | сверочный запрос + тест |
| Упаковано не больше заказанного | сервисный слой в транзакции |
| Коробка сканируется один раз | `UNIQUE (batch_id, barcode)` |
| Штрихкод уникален в системе | `UNIQUE` в `shipment_box`, `UNIQUE (batch_id, barcode)` |
| Переход статуса разрешён схемой | сервисный слой |
| В системе есть хотя бы один администратор | сервисный слой при удалении и смене роли |
| Позиция с движениями не удаляется | `ON DELETE RESTRICT` + архивация |

## 6. Индексы под конкретные экраны

Индексы заданы не «на всякий случай», а под запросы, которые действительно
выполняются:

| Экран | Запрос | Индекс |
|---|---|---|
| Заказы, вкладки и фильтры | `direction`, `status`, сортировка по дате | `order_list_idx` |
| Заказы, поиск по номеру | `number LIKE '3029%'` | `order_number_idx` (`text_pattern_ops`) |
| Справочник, поиск | наименование, артикул, код 1С | `catalog_item_search_idx` (GIN) |
| Остатки, «ниже минимума» | `qty - reserved < min_qty` | частичный `stock_balance_below_min_idx` |
| Карточка товара, история | `item_id`, сортировка по дате | `stock_movement_item_idx` |
| Отгрузка и приёмка, списки | `status`, сортировка по дате | `*_list_idx` |
| Журнал печати по коробке | `barcode` | `print_job_barcode_idx` |

## 7. Миграции и начальные данные

**Миграции.** Alembic, по одной ревизии на осмысленное изменение. Первая
ревизия — вся схема из раздела 3. Правило: каждая ревизия должна накатываться и
на пустую базу, и на базу с данными; необратимые изменения (удаление колонки)
разбиваются на два релиза — сначала перестаём писать, потом удаляем.

**Начальные данные** (отдельный скрипт `seed.py`, не миграция):

- роли `manager`, `stockman`, `admin` и матрица прав по умолчанию;
- склады из текущего JSON-файла;
- 22 позиции номенклатуры;
- один администратор с паролем из переменной окружения;
- шаблон этикетки коробки.

**Перенос текущих данных.** Разовый скрипт читает `desktop/mock_data.json` и
переносит справочники, остатки, пользователей, заказы и права. Отдельно
восстанавливаются связи: строки заказов ссылаются на артикулы, склады
сопоставляются по имени. Прогресс упаковки и сканирования не переносится — это
рабочее состояние, а не документы.

## 8. Сверка и обслуживание

Запрос, который должен возвращать пустой результат — расхождение баланса и
журнала:

```sql
SELECT b.item_id, b.warehouse_id, b.qty AS balance, coalesce(m.total, 0) AS movements
FROM stock_balance b
LEFT JOIN (
    SELECT item_id, warehouse_id, sum(delta) AS total
    FROM stock_movement
    WHERE type IN ('receipt','shipment','writeoff','recount')
    GROUP BY item_id, warehouse_id
) m ON m.item_id = b.item_id AND m.warehouse_id = b.warehouse_id
WHERE b.qty <> coalesce(m.total, 0);
```

Регламентные задания:

| Что | Когда |
|---|---|
| `pg_dump` полностью, копия на отдельный носитель | ежедневно ночью |
| Проверка восстановления дампа на тестовом стенде | ежемесячно |
| Удаление `idempotency_key` старше 24 часов | ежечасно |
| Удаление отозванных и просроченных `refresh_token` | ежедневно |
| Сверочный запрос выше | ежедневно, расхождение — в лог и уведомление |
| `VACUUM ANALYZE` | автовакуумом, ручного не требуется |

Хранение: `audit_log` и `stock_movement` не чистятся — это учётные данные.
При заметном росте `audit_log` переводится на секционирование по месяцам.

## 9. Оценка объёмов

Исходя из 20 пользователей и текущего оборота:

| Таблица | Прирост в год | Через 5 лет |
|---|---|---|
| `order` | ~10 000 | 50 000 |
| `order_position` | ~30 000 | 150 000 |
| `stock_movement` | ~100 000 | 500 000 |
| `shipment_box` | ~40 000 | 200 000 |
| `receipt_scan` | ~40 000 | 200 000 |
| `audit_log` | ~200 000 | 1 000 000 |

Суммарно единицы гигабайт за пять лет. Для PostgreSQL это ничто; 40 ГБ диска на
сервере хватит с большим запасом, включая место под дампы.

## 10. Критерии приёмки

- [ ] Первая миграция создаёт схему из раздела 3 на чистой базе без ошибок.
- [ ] Сид наполняет роли, права, склады, номенклатуру и администратора.
- [ ] Скрипт переноса из `prozapas.json` отрабатывает на реальном файле, число
      заказов, пользователей и позиций совпадает.
- [ ] Все ограничения из раздела 5 покрыты тестами, включая отрицательные
      сценарии (списание в минус, двойной скан, дубль штрихкода).
- [ ] Сверочный запрос из раздела 8 возвращает пусто после прогона всех
      сценарных тестов бэкенда.
- [ ] `EXPLAIN` на списках заказов, остатков и справочника показывает
      использование индексов, а не последовательный скан.
