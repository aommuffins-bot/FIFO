"""
db_engine.py — 資料層 v2：SQLAlchemy Core 引擎（同時支援 SQLite 與 PostgreSQL）
"""

import os
from contextlib import contextmanager
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, Float, String,
    Text, DateTime, ForeignKey, CheckConstraint, text
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///aom_cafe_inventory.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
_engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
metadata = MetaData()

# 門店主檔
stores = Table(
    "stores", metadata,
    Column("store_id", Integer, primary_key=True, autoincrement=True),
    Column("store_name", String(100), nullable=False),
    Column("address", String(200)),
    Column("is_active", Integer, default=1),
)

# 使用者與角色
users = Table(
    "users", metadata,
    Column("user_id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(50), nullable=False, unique=True),
    Column("password_hash", String(200), nullable=False),
    Column("password_salt", String(64), nullable=False),
    Column("role", String(20), nullable=False),
    Column("store_id", Integer, ForeignKey("stores.store_id"), nullable=True),
    Column("is_active", Integer, default=1),
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("role IN ('admin','staff')", name="ck_users_role"),
)

# 商品主檔
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

# 批次（FIFO 核心）
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
    Column("origin", String(100)),
    Column("flavor", Text),
    Column("process", String(30)),
    Column("roast_date", String(10)),
    Column("lot_ref", String(100)),
    Column("created_by", Integer, ForeignKey("users.user_id"), nullable=True),
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
)

# 交易單頭
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

# 交易明細（FIFO 扣帳分配）
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
    """建立所有資料表（若不存在），並確保預設門店 (store_id=1) 存在。"""
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
    """提供資料庫連線的 context manager"""
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