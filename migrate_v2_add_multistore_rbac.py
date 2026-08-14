"""
migrate_v2_add_multistore_rbac.py -- 資料庫遷移腳本（離線版 -> 橋接架構升級）
------------------------------------------------------------------------
若已使用離線版 aom_cafe_inventory.db（僅有products/batches/transactions/
txn_allocations四表），執行本腳本可安全就地升級，新增：
  - stores 表（多門店主檔）
  - users 表（帳號與角色）
  - batches.store_id / transactions.store_id 欄位（預設值=1，既有資料自動歸入店1）

執行方式：
    python migrate_v2_add_multistore_rbac.py

本腳本可重複執行（具備ALTER TABLE前的欄位存在性檢查），不會重複新增欄位。
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "aom_cafe_inventory.db"


def column_exists(conn, table, column) -> bool:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def table_exists(conn, table) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")  # 遷移期間暫時關閉，避免中間態外鍵衝突

    # 1) stores 表
    if not table_exists(conn, "stores"):
        conn.execute("""
            CREATE TABLE stores (
                store_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                address TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn.execute(
            "INSERT INTO stores (store_id, store_name, address, is_active) VALUES (1, ?, ?, 1)",
            ("A.O.M Cafe 台中旗艦店（首店）", "台中市（既有資料自動歸屬本店）")
        )
        print("已建立 stores 表，並將既有資料歸屬於 store_id=1")
    else:
        print("stores 表已存在，略過")

    # 2) users 表
    if not table_exists(conn, "users"):
        conn.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','staff')),
                store_id INTEGER REFERENCES stores(store_id),
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        print("已建立 users 表（尚無帳號，請執行 auth.seed_default_admin() 建立預設帳號）")
    else:
        print("users 表已存在，略過")

    # 3) batches.store_id
    if not column_exists(conn, "batches", "store_id"):
        conn.execute("ALTER TABLE batches ADD COLUMN store_id INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE batches ADD COLUMN created_by INTEGER")
        print("已為 batches 表新增 store_id / created_by 欄位（既有資料預設歸屬 store_id=1）")
    else:
        print("batches.store_id 已存在，略過")

    # 4) transactions.store_id
    if not column_exists(conn, "transactions", "store_id"):
        conn.execute("ALTER TABLE transactions ADD COLUMN store_id INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE transactions ADD COLUMN created_by INTEGER")
        print("已為 transactions 表新增 store_id / created_by 欄位")
    else:
        print("transactions.store_id 已存在，略過")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print("\n遷移完成！可接續執行 api_server.py 啟動線上版服務。")


if __name__ == "__main__":
    migrate()
