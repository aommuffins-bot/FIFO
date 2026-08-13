-- postgres_schema.sql -- 正式生產環境PostgreSQL DDL（橋接架構 第2點：資料庫升級參考）
-- ------------------------------------------------------------------------
-- 說明：若採用db_engine.py（SQLAlchemy Core），僅需設定環境變數
--   DATABASE_URL=postgresql+psycopg2://user:password@host:5432/aom_cafe
-- 並執行 db_engine.init_db() 即可自動建表，本檔案僅供DBA參考直接手動部署，
-- 或用於資料庫版本控管（如配合Alembic/Flyway）。
--
-- 與SQLite版主要差異：
--   1. INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
--   2. TEXT -> VARCHAR(n) / TEXT（PostgreSQL兩者皆可，此處沿用TEXT以簡化）
--   3. datetime('now','localtime') -> CURRENT_TIMESTAMP
--   4. 新增外鍵約束的 ON DELETE 策略（SQLite預設較寬鬆，正式環境建議明確指定）

CREATE TABLE IF NOT EXISTS stores (
    store_id     SERIAL PRIMARY KEY,
    store_name   VARCHAR(100) NOT NULL,
    address      VARCHAR(200),
    is_active    SMALLINT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    user_id        SERIAL PRIMARY KEY,
    username       VARCHAR(50) NOT NULL UNIQUE,
    password_hash  VARCHAR(200) NOT NULL,
    password_salt  VARCHAR(64) NOT NULL,
    role           VARCHAR(20) NOT NULL CHECK (role IN ('admin','staff')),
    store_id       INTEGER REFERENCES stores(store_id) ON DELETE SET NULL,
    is_active      SMALLINT DEFAULT 1,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    sku_no              INTEGER PRIMARY KEY,
    continent           VARCHAR(20) NOT NULL,
    country             VARCHAR(30) NOT NULL,
    name                VARCHAR(100) NOT NULL,
    process              VARCHAR(30),
    variety             VARCHAR(50),
    flavor              TEXT,
    rating              VARCHAR(10),
    strategy            VARCHAR(20),
    batch_hint          VARCHAR(30),
    cost_range_raw      VARCHAR(50),
    cost_ntd_100g_raw   VARCHAR(50),
    retail_ntd_100g_raw VARCHAR(50),
    margin_pct_raw      VARCHAR(20),
    notes               TEXT,
    season              VARCHAR(30),
    importer            VARCHAR(50),
    shelf_life_months   INTEGER DEFAULT 9,
    is_active           SMALLINT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id             SERIAL PRIMARY KEY,
    sku_no               INTEGER NOT NULL REFERENCES products(sku_no),
    store_id             INTEGER NOT NULL DEFAULT 1 REFERENCES stores(store_id),
    receive_date         DATE NOT NULL,
    qty_received_g       NUMERIC(12,2) NOT NULL,
    qty_remaining_g      NUMERIC(12,2) NOT NULL,
    unit_cost_ntd_per_g  NUMERIC(10,4) NOT NULL,
    supplier             VARCHAR(100),
    lot_ref              VARCHAR(100),
    created_by           INTEGER REFERENCES users(user_id),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id               SERIAL PRIMARY KEY,
    sku_no               INTEGER NOT NULL REFERENCES products(sku_no),
    store_id             INTEGER NOT NULL DEFAULT 1 REFERENCES stores(store_id),
    txn_type             VARCHAR(10) NOT NULL CHECK (txn_type IN ('IN','OUT','ADJUST')),
    txn_date             DATE NOT NULL,
    qty_g                NUMERIC(12,2) NOT NULL,
    unit_price_ntd_per_g NUMERIC(10,4),
    total_amount_ntd     NUMERIC(14,2),
    total_cogs_ntd       NUMERIC(14,2),
    gross_profit_ntd     NUMERIC(14,2),
    channel              VARCHAR(20),
    reference            VARCHAR(100),
    created_by           INTEGER REFERENCES users(user_id),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS txn_allocations (
    alloc_id             SERIAL PRIMARY KEY,
    txn_id               INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    batch_id             INTEGER NOT NULL REFERENCES batches(batch_id),
    qty_g                NUMERIC(12,2) NOT NULL,
    unit_cost_ntd_per_g  NUMERIC(10,4) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batches_sku_store ON batches(sku_no, store_id, receive_date);
CREATE INDEX IF NOT EXISTS idx_txn_sku_store ON transactions(sku_no, store_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_txn_store_date ON transactions(store_id, txn_date);

INSERT INTO stores (store_id, store_name, address, is_active)
VALUES (1, 'A.O.M Cafe 台中旗艦店', '台中市', 1)
ON CONFLICT (store_id) DO NOTHING;
