"""
db_engine.py — 資料層 v2：SQLAlchemy Core引擎（同時支援SQLite與PostgreSQL）
------------------------------------------------------------------------
橋接架構第2點【資料庫升級】的實作核心。

設計原則：
  - 使用 SQLAlchemy Core（非ORM），保留與原database.py相近的「寫SQL」風格，
    但透過SQLAlchemy的Engine抽象層，讓同一套程式碼可切換SQLite/PostgreSQL，
    僅需改變環境變數 DATABASE_URL，無需修改任何查詢邏輯。
  - Schema新增：
      stores          多門店主檔（橋接架構第5點）
      users / roles   使用者與角色（橋接架構第4點：店員/管理者）
      batches.store_id / transactions.store_id  各批次與交易歸屬門店

環境變數：
  DATABASE_URL
    - 未設定時預設："sqlite:///aom_cafe_inventory.db"（離線開發模式，與CLI版相容）
    - 生產環境設定為："postgresql+psycopg2://user:password@host:5432/aom_cafe"

使用方式：
  from db_engine import get_engine, get_conn
  with get_conn() as conn:
      conn.execute(text("SELECT ..."))
"""

import os
from contextlib import contextmanager
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, Float, String,
    Text, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, text
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///aom_cafe_inventory.db")

# SQLite需要 check_same_thread=False 才能在多執行緒的FastAPI環境下使用；
# PostgreSQL則不需要此參數，故依dialect動態決定connect_args。
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

_engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
metadata = MetaData()

# ------------------------------------------------------------------
# 門店主檔（橋接架構 第5點：多門店支援）
# ------------------------------------------------------------------
stores = Table(
    "stores", metadata,
    Column("store_id", Integer, primary_key=True, autoincrement=True),
    Column("store_name", String(100), nullable=False),
    Column("address", String(200)),
    Column("is_active", Integer, default=1),
)

# ------------------------------------------------------------------
# 使用者與角色（橋接架構 第4點：權限管理）
# ------------------------------------------------------------------
users = Table(
    "users", metadata,
    Column("user_id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(50), nullable=False, unique=True),
    Column("password_hash", String(200), nullable=False),
    Column("password_salt", String(64), nullable=False),
    Column("role", String(20), nullable=False),   # 'admin'（管理者）| 'staff'（店員）
    Column("store_id", Integer, ForeignKey("stores.store_id"), nullable=True),
    Column("is_active", Integer, default=1),
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("role IN ('admin','staff')", name="ck_users_role"),
)

# ------------------------------------------------------------------
# 商品主檔（100 SKU）— 與離線版schema對應
# ------------------------------------------------------------------
products = Table(
    "products", metadata,
    Column("sku_no", Integer, primary_key=True),
    Column("continent", String(20), nullable=False),
    Column("country", String(30), nullable=False),
    Column("name", String(100), nullable=False),
    Column("process", String(30)),
    Column("variety", String(50)),
    Column("flavor", Text),
    Column("rating", String(10)),
    Column("strategy", String(20)),
    Column("batch_hint", String(30)),
    Column("cost_range_raw", String(50)),
    Column("cost_ntd_100g_raw", String(50)),
    Column("retail_ntd_100g_raw", String(50)),
    Column("margin_pct_raw", String(20)),
    Column("notes", Text),
    Column("season", String(30)),
    Column("importer", String(50)),
    Column("shelf_life_months", Integer, default=9),
    Column("is_active", Integer, default=1),
)

# ------------------------------------------------------------------
# 批次（FIFO核心）— 新增 store_id 歸屬門店
# ------------------------------------------------------------------
batches = Table(
    "batches", metadata,
    Column("batch_id", Integer, primary_key=True, autoincrement=True),
    Column("sku_no", Integer, ForeignKey("products.sku_no"), nullable=False),
    Column("store_id", Integer, ForeignKey("stores.store_id"), nullable=False, server_default="1"),
    Column("receive_date", String(10), nullable=False),
    Column("qty_received_g", Float, nullable=False),
    Column("qty_remaining_g", Float, nullable=False),
    Column("unit_cost_ntd_per_g", Float, nullable=False),
    Column("supplier", String(100)),
    Column("lot_ref", String(100)),
    Column("created_by", Integer, ForeignKey("users.user_id"), nullable=True),
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
)

# ------------------------------------------------------------------
# 交易單頭 — 新增 store_id 歸屬門店 與 created_by 操作人員
# ------------------------------------------------------------------
transactions = Table(
    "transactions", metadata,
    Column("txn_id", Integer, primary_key=True, autoincrement=True),
    Column("sku_no", Integer, ForeignKey("products.sku_no"), nullable=False),
    Column("store_id", Integer, ForeignKey("stores.store_id"), nullable=False, server_default="1"),
    Column("txn_type", String(10), nullable=False),
    Column("txn_date", String(10), nullable=False),
    Column("qty_g", Float, nullable=False),
    Column("unit_price_ntd_per_g", Float),
    Column("total_amount_ntd", Float),
    Column("total_cogs_ntd", Float),
    Column("gross_profit_ntd", Float),
    Column("channel", String(20)),
    Column("reference", String(100)),
    Column("created_by", Integer, ForeignKey("users.user_id"), nullable=True),
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("txn_type IN ('IN','OUT','ADJUST')", name="ck_txn_type"),
)

txn_allocations = Table(
    "txn_allocations", metadata,
    Column("alloc_id", Integer, primary_key=True, autoincrement=True),
    Column("txn_id", Integer, ForeignKey("transactions.txn_id"), nullable=False),
    Column("batch_id", Integer, ForeignKey("batches.batch_id"), nullable=False),
    Column("qty_g", Float, nullable=False),
    Column("unit_cost_ntd_per_g", Float, nullable=False),
)


def get_engine():
    return _engine


def init_db():
    """建立所有資料表（若不存在），並確保預設門店(store_id=1)存在。"""
    metadata.create_all(_engine)
    with _engine.begin() as conn:
        exists = conn.execute(text("SELECT COUNT(*) FROM stores")).scalar()
        if not exists:
            conn.execute(
                stores.insert().values(store_id=1, store_name="A.O.M Cafe 台中旗艦店",
                                        address="台中市（首店，示範資料）", is_active=1)
            )


@contextmanager
def get_conn():
    """
    提供資料庫連線的context manager，行為與離線版database.py之get_conn()一致，
    確保 fifo_engine.py 呼叫端不需感知底層是SQLite還是PostgreSQL。
    """
    conn = _engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()
