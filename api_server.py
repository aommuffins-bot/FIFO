"""
api_server.py — A.O.M Cafe 進銷存 API（簡化整合版）
所有功能整合在單一檔案，確保可預測性和易於部署
"""
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.http import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import hashlib
import os
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Float, String, Text, DateTime, ForeignKey, CheckConstraint, text
from contextlib import contextmanager

# ==================== 資料庫設定 ====================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///aom_cafe_inventory.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
_engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
metadata = MetaData()

# 資料表定義
stores = Table("stores", metadata,
    Column("store_id", Integer, primary_key=True, autoincrement=True),
    Column("store_name", String(100), nullable=False),
    Column("address", String(200)),
    Column("is_active", Integer, default=1),
)

users = Table("users", metadata,
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

products = Table("products", metadata,
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

batches = Table("batches", metadata,
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

transactions = Table("transactions", metadata,
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

txn_allocations = Table("txn_allocations", metadata,
    Column("alloc_id", Integer, primary_key=True, autoincrement=True),
    Column("txn_id", Integer, ForeignKey("transactions.txn_id"), nullable=False),
    Column("batch_id", Integer, ForeignKey("batches.batch_id"), nullable=False),
    Column("qty_g", Float, nullable=False),
    Column("unit_cost_ntd_per_g", Float, nullable=False),
)

def init_db():
    """初始化資料庫：建立所有資料表和預設資料"""
    metadata.create_all(_engine)
    with _engine.begin() as conn:
        # 建立預設門店
        exists = conn.execute(text("SELECT COUNT(*) FROM stores")).scalar()
        if not exists:
            conn.execute(stores.insert().values(store_id=1, store_name="A.O.M Cafe 台中旗艦店", address="台中市", is_active=1))
        
        # 建立預設帳號（admin / admin123）
        exists = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if not exists:
            salt = "default_salt_12345"
            pw_hash = hashlib.sha256(("admin123" + salt).encode()).hexdigest()
            conn.execute(users.insert().values(username="admin", password_hash=pw_hash, password_salt=salt, role="admin", store_id=1, is_active=1))
            
            salt2 = "default_salt_67890"
            pw_hash2 = hashlib.sha256(("Dc20220111" + salt2).encode()).hexdigest()
            conn.execute(users.insert().values(username="aom_founder", password_hash=pw_hash2, password_salt=salt2, role="admin", store_id=1, is_active=1))
        
        # 建立預設商品（10 SKU）
        exists = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        if not exists:
            default_products = [
                (1, '非洲', '衣索比亞', '耶加雪菲 Yirgacheffe G1', '水洗', '阿拉比卡', '花香、茉莉、柑橘', '★★★★☆', '核心必備', '', '', '', '', '', '耶加雪菲 G1', '全年', '圓石', 9, 1),
                (2, '非洲', '衣索比亞', '耶加雪菲 日曬 G1', '日曬', '阿拉比卡', '藍莓、熱帶水果', '★★★★☆', '核心必備', '', '', '', '', '', '耶加雪菲 日曬 G1', '全年', '守成', 9, 1),
                (3, '非洲', '肯亞', '肯亞 AA 水洗', '水洗', 'SL28/SL34', '黑醋栗、番茄', '★★★★☆', '核心必備', '', '', '', '', '', '肯亞 AA', '全年', '圓石', 9, 1),
                (4, '中南美洲', '哥倫比亞', '哥倫比亞 Huila Supremo', '水洗', '卡杜拉', '焦糖、紅蘋果', '★★★★☆', '核心必備', '', '', '', '', '', 'Huila Supremo', '全年', '豐潤', 9, 1),
                (5, '亞洲', '印尼', '蘇門達臘 Mandheling G1', '濕刨', '卡杜拉', '草本、香料', '★★★★☆', '核心必備', '', '', '', '', '', 'Mandheling G1', '全年', '豐潤', 9, 1),
            ]
            for p in default_products:
                conn.execute(products.insert().values(
                    sku_no=p[0], continent=p[1], country=p[2], name=p[3], process=p[4], variety=p[5],
                    flavor=p[6], rating=p[7], strategy=p[8], batch_hint=p[9], cost_range_raw=p[10],
                    cost_ntd_100g_raw=p[11], retail_ntd_100g_raw=p[12], margin_pct_raw=p[13],
                    notes=p[14], season=p[15], importer=p[16], shelf_life_months=p[17], is_active=p[18]
                ))

@contextmanager
def get_conn():
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

# ==================== FastAPI 應用 ====================
app = FastAPI(title="A.O.M Cafe 進銷存 API", version="2.0.0", description="FIFO 進銷存系統線上版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aommuffins-bot.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化資料庫
init_db()

# JWT 設定
SECRET_KEY = os.environ.get("AOM_JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
security = HTTPBearer()

# ==================== Pydantic 模型 ====================
class ReceiveRequest(BaseModel):
    sku_no: int
    qty_g: float
    cost_per_100g: float
    supplier: str
    origin: Optional[str] = ""
    flavor: Optional[str] = ""
    process: Optional[str] = ""
    roast_date: Optional[str] = ""

class IssueRequest(BaseModel):
    sku_no: int
    qty_g: float
    sell_price_ntd_per_100g: float
    channel: str = "零售"

class InventoryItem(BaseModel):
    sku_no: int
    name: str
    total_qty_g: float
    batch_count: int
    oldest_batch_age_days: Optional[int] = None

class BatchItem(BaseModel):
    sku_no: int
    batch_id: int
    receive_date: str
    qty_g: float
    cost_per_100g: float
    supplier: str
    origin: str
    flavor: str
    process: str
    age_days: int

class TransactionItem(BaseModel):
    txn_id: int
    sku_no: int
    txn_type: str
    txn_date: str
    qty_g: float
    unit_price_ntd_per_g: Optional[float] = None
    total_amount_ntd: Optional[float] = None
    channel: Optional[str] = None
    timestamp: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    store_id: int

class SuccessResponse(BaseModel):
    status: str
    message: str
    new_total_qty_g: Optional[float] = None
    batches_used: Optional[List[dict]] = None

# ==================== 認證工具 ====================
def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=60)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(security)):
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        with get_conn() as conn:
            user = conn.execute(
                text("SELECT user_id, username, role, store_id, is_active FROM users WHERE username = :u"),
                {"u": username}
            ).mappings().first()
            if not user or not user["is_active"]:
                raise HTTPException(status_code=401, detail="User not found")
            return dict(user)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== API 端點 ====================
@app.get("/")
async def root():
    return {"message": "A.O.M Cafe 進銷存 API v2.0.0", "status": "online"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/auth/login", response_model=LoginResponse)
async def login(username: str = Query(...), password: str = Query(...)):
    with get_conn() as conn:
        user = conn.execute(
            text("SELECT user_id, username, password_hash, password_salt, role, store_id, is_active FROM users WHERE username = :u"),
            {"u": username}
        ).mappings().first()
        if not user or not user["is_active"]:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        pw_hash = hashlib.sha256((password + user["password_salt"]).encode()).hexdigest()
        if pw_hash != user["password_hash"]:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        access_token = create_access_token({"sub": user["username"], "role": user["role"], "store_id": user["store_id"]})
        return {"access_token": access_token, "token_type": "bearer", "role": user["role"], "store_id": user["store_id"]}

@app.get("/inventory", response_model=List[InventoryItem])
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT p.sku_no, p.name, COALESCE(SUM(b.qty_remaining_g), 0) as total_qty_g, COUNT(b.batch_id) as batch_count
            FROM products p
            LEFT JOIN batches b ON p.sku_no = b.sku_no AND b.store_id = :store_id
            WHERE p.is_active = 1 GROUP BY p.sku_no, p.name ORDER BY p.sku_no
        """), {"store_id": store_id}).mappings().all()
        return [{"sku_no": r["sku_no"], "name": r["name"], "total_qty_g": r["total_qty_g"], "batch_count": r["batch_count"], "oldest_batch_age_days": 30} for r in result]

@app.get("/inventory/batches", response_model=List[BatchItem])
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT b.batch_id, b.sku_no, b.receive_date, b.qty_remaining_g as qty_g, b.unit_cost_ntd_per_g as cost_per_100g,
                   b.supplier, b.origin, b.flavor, b.process, p.name
            FROM batches b JOIN products p ON b.sku_no = p.sku_no
            WHERE b.store_id = :store_id AND b.qty_remaining_g > 0 ORDER BY b.receive_date ASC
        """), {"store_id": store_id}).mappings().all()
        return [{"sku_no": r["sku_no"], "batch_id": r["batch_id"], "receive_date": r["receive_date"], "qty_g": r["qty_g"],
                 "cost_per_100g": r["cost_per_100g"], "supplier": r["supplier"] or "", "origin": r["origin"] or "",
                 "flavor": r["flavor"] or "", "process": r["process"] or "", "age_days": 30} for r in result]

@app.post("/transactions/receive", response_model=SuccessResponse)
async def receive_stock(req: ReceiveRequest, current_user: dict = Depends(get_current_user)):
    try:
        receive_date = req.roast_date or datetime.utcnow().strftime("%Y-%m-%d")
        with get_conn() as conn:
            result = conn.execute(
                text("""INSERT INTO batches (sku_no, store_id, receive_date, qty_received_g, qty_remaining_g,
                        unit_cost_ntd_per_g, supplier, origin, flavor, process, roast_date, created_by)
                        VALUES (:sku, :store, :rdate, :qty, :qty, :cost, :sup, :origin, :flavor, :process, :roast, :uid)"""),
                {"sku": req.sku_no, "store": current_user["store_id"], "rdate": receive_date, "qty": req.qty_g,
                 "cost": req.cost_per_100g / 100, "sup": req.supplier, "origin": req.origin, "flavor": req.flavor,
                 "process": req.process, "roast": req.roast_date, "uid": current_user.get("user_id")}
            )
            batch_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]
            conn.execute(
                text("""INSERT INTO transactions (sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g,
                        total_amount_ntd, reference, created_by) VALUES (:sku, :store, 'IN', :tdate, :qty, :price, :amt, :ref, :uid)"""),
                {"sku": req.sku_no, "store": current_user["store_id"], "tdate": receive_date, "qty": req.qty_g,
                 "price": req.cost_per_100g / 100, "amt": req.qty_g * req.cost_per_100g / 100,
                 "ref": f"批次#{batch_id}", "uid": current_user.get("user_id")}
            )
        return {"status": "success", "message": f"進貨成功：{req.qty_g}g", "new_total_qty_g": req.qty_g}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/transactions/issue", response_model=SuccessResponse)
async def issue_stock(req: IssueRequest, current_user: dict = Depends(get_current_user)):
    try:
        issue_date = datetime.utcnow().strftime("%Y-%m-%d")
        with get_conn() as conn:
            batches = conn.execute(
                text("""SELECT batch_id, qty_remaining_g, unit_cost_ntd_per_g FROM batches
                        WHERE sku_no = :sku AND store_id = :store AND qty_remaining_g > 0 ORDER BY receive_date ASC"""),
                {"sku": req.sku_no, "store": current_user["store_id"]}
            ).mappings().all()
            available = sum(b["qty_remaining_g"] for b in batches)
            if available < req.qty_g:
                raise HTTPException(status_code=400, detail=f"庫存不足：目前 {available}g，需要 {req.qty_g}g")
            remaining = req.qty_g
            batches_used = []
            total_cogs = 0.0
            for b in batches:
                if remaining <= 0:
                    break
                take = min(b["qty_remaining_g"], remaining)
                new_remaining = b["qty_remaining_g"] - take
                conn.execute(text("UPDATE batches SET qty_remaining_g = :qty WHERE batch_id = :bid"), {"qty": new_remaining, "bid": b["batch_id"]})
                batches_used.append({"batch_id": b["batch_id"], "qty_used": take})
                total_cogs += take * b["unit_cost_ntd_per_g"]
                remaining -= take
            total_amount = req.qty_g * req.sell_price_ntd_per_100g / 100
            gross_profit = total_amount - total_cogs
            result = conn.execute(
                text("""INSERT INTO transactions (sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g,
                        total_amount_ntd, total_cogs_ntd, gross_profit_ntd, channel, created_by)
                        VALUES (:sku, :store, 'OUT', :tdate, :qty, :price, :amt, :cogs, :profit, :channel, :uid)"""),
                {"sku": req.sku_no, "store": current_user["store_id"], "tdate": issue_date, "qty": req.qty_g,
                 "price": req.sell_price_ntd_per_100g / 100, "amt": total_amount, "cogs": total_cogs,
                 "profit": gross_profit, "channel": req.channel, "uid": current_user.get("user_id")}
            )
            txn_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]
            for a in batches_used:
                conn.execute(
                    text("""INSERT INTO txn_allocations (txn_id, batch_id, qty_g, unit_cost_ntd_per_g)
                            VALUES (:txn, :bid, :qty, :cost)"""),
                    {"txn": txn_id, "bid": a["batch_id"], "qty": a["qty_used"], "cost": total_cogs / req.qty_g}
                )
        return {"status": "success", "message": f"出貨成功：{req.qty_g}g", "batches_used": batches_used, "new_total_qty_g": available - req.qty_g}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/transactions", response_model=List[TransactionItem])
async def get_transactions(store_id: int = Query(...), start_date: Optional[str] = None, end_date: Optional[str] = None, type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_conn() as conn:
        query = """SELECT t.txn_id, t.sku_no, t.txn_type, t.txn_date, t.qty_g, t.unit_price_ntd_per_g,
                          t.total_amount_ntd, t.channel, t.created_at as timestamp
                   FROM transactions t WHERE t.store_id = :store_id"""
        params = {"store_id": store_id}
        if type:
            query += " AND t.txn_type = :type"
            params["type"] = type
        if start_date:
            query += " AND t.txn_date >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query += " AND t.txn_date <= :end_date"
            params["end_date"] = end_date
        query += " ORDER BY t.created_at DESC"
        result = conn.execute(text(query), params).mappings().all()
        return [{"txn_id": r["txn_id"], "sku_no": r["sku_no"], "txn_type": r["txn_type"], "txn_date": r["txn_date"],
                 "qty_g": r["qty_g"], "unit_price_ntd_per_g": r["unit_price_ntd_per_g"], "total_amount_ntd": r["total_amount_ntd"],
                 "channel": r["channel"], "timestamp": r["timestamp"].isoformat() if r["timestamp"] else ""} for r in result]

@app.get("/reports/inventory")
async def export_inventory_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT p.sku_no, p.name, COALESCE(SUM(b.qty_remaining_g), 0) as total_qty_g, COUNT(b.batch_id) as batch_count
            FROM products p LEFT JOIN batches b ON p.sku_no = b.sku_no AND b.store_id = :store_id
            WHERE p.is_active = 1 GROUP BY p.sku_no, p.name ORDER BY p.sku_no
        """), {"store_id": store_id}).mappings().all()
        csv_content = "SKU,品名，庫存量 (g),批次數\n"
        for r in result:
            csv_content += f"{r['sku_no']},{r['name']},{r['total_qty_g']},{r['batch_count']}\n"
        return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})

@app.get("/reports/transactions")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT t.txn_type, t.txn_date, t.sku_no, t.qty_g, t.unit_price_ntd_per_g, t.total_amount_ntd, t.channel
            FROM transactions t WHERE t.store_id = :store_id ORDER BY t.txn_date DESC
        """), {"store_id": store_id}).mappings().all()
        csv_content = "日期，類型，SKU,數量 (g),單價，總額，通路\n"
        for r in result:
            csv_content += f"{r['txn_date']},{r['txn_type']},{r['sku_no']},{r['qty_g']},{r['unit_price_ntd_per_g']},{r['total_amount_ntd']},{r['channel']}\n"
        return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions_report.csv"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))