"""
api_server.py -- API層：FastAPI包裝fifo_engine_v2為REST端點（橋接架構 第1點）
------------------------------------------------------------------------
啟動方式：
    pip install -r requirements.txt
    uvicorn api_server:app --reload --port 8000

首次啟動會自動：
  1. 初始化資料庫schema（含stores/users/products/batches/transactions等表）
  2. 建立預設門店(store_id=1)
  3. 建立預設帳號 admin/aomcafe2026（管理者）、staff01/staff2026（店員）

★ 商業邏輯零重寫 ★
本檔案所有端點皆直接呼叫fifo_engine_v2.py既有函式，未新增任何FIFO運算邏輯，
確保離線CLI版與線上API版之財務計算結果100%一致。
"""

from typing import Optional, List
from datetime import date
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import auth
import fifo_engine_v2 as fifo
from db_engine import init_db, get_conn, products as products_tbl, stores as stores_tbl
from sqlalchemy import text

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="A.O.M Cafe 進銷存 API", version="2.0.0",
               description="FIFO進銷存系統線上版（橋接自離線版fifo_engine.py）")

# CORS設定：允許GitHub Pages存取
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aommuffins-bot.github.io",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 其他路由定義...

# 開發階段開放所有來源；正式上線請改為白名單（如僅允許前端網域）
app.add_middleware(
    CORSMiddleware, allow_origins=["https://aomcafefifo.jimdofree.com"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@app.on_event("startup")
def on_startup():
    init_db()
    auth.seed_default_admin()
    from seed_100sku import seed as seed_products
    seed_products()   # 自動匯入100 SKU，內部已用INSERT OR REPLACE，重複啟動不會重複新增


# ------------------------------------------------------------------
# Pydantic 請求/回應模型
# ------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    store_id: Optional[int]


class ReceiveStockRequest(BaseModel):
    sku_no: int
    qty_kg: float
    cost_ntd_per_100g: float
    supplier: Optional[str] = None
    lot_ref: Optional[str] = None
    receive_date: Optional[str] = None
    store_id: int = 1


class IssueStockRequest(BaseModel):
    sku_no: int
    qty_g: float
    sell_price_ntd_per_100g: float
    channel: str = "零售"
    reference: Optional[str] = None
    issue_date: Optional[str] = None
    store_id: int = 1


# ------------------------------------------------------------------
# 權限驗證依賴（Dependency）
# ------------------------------------------------------------------
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = auth.decode_token(token)
    except auth.TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return payload


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """僅限管理者（admin）存取：進貨、成本調整、完整損益報表"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                             detail="此操作僅限管理者（admin）執行")
    return user


def require_staff_or_admin(user: dict = Depends(get_current_user)) -> dict:
    """店員與管理者皆可存取：出貨、庫存查詢"""
    if user.get("role") not in ("admin", "staff"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="權限不足")
    return user


# ------------------------------------------------------------------
# 認證端點
# ------------------------------------------------------------------
@app.post("/auth/login", response_model=TokenResponse, tags=["認證"])
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = auth.authenticate(form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    token = auth.encode_token({
        "user_id": user["user_id"], "username": user["username"],
        "role": user["role"], "store_id": user["store_id"]
    })
    return TokenResponse(access_token=token, role=user["role"], store_id=user["store_id"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str  # 'admin' | 'staff'
    store_id: int = 1


@app.post("/auth/users", tags=["認證"])
def create_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    """新增使用者帳號，僅限管理者操作"""
    try:
        uid = auth.create_user(req.username, req.password, req.role, req.store_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user_id": uid, "username": req.username, "role": req.role}


# ------------------------------------------------------------------
# 門店管理（橋接架構 第5點）
# ------------------------------------------------------------------
class StoreRequest(BaseModel):
    store_name: str
    address: Optional[str] = None


@app.get("/stores", tags=["門店"])
def list_stores(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(text("SELECT * FROM stores WHERE is_active = 1")).mappings().all()
    return [dict(r) for r in rows]


@app.post("/stores", tags=["門店"])
def create_store(req: StoreRequest, admin: dict = Depends(require_admin)):
    """新增門店，僅限管理者操作（對應募資計畫「儲備資金啟動第二門店」情境）"""
    with get_conn() as conn:
        result = conn.execute(
            stores_tbl.insert().values(store_name=req.store_name, address=req.address, is_active=1)
        )
        new_id = result.inserted_primary_key[0]
    return {"store_id": new_id, "store_name": req.store_name}


# ------------------------------------------------------------------
# 商品主檔查詢
# ------------------------------------------------------------------
@app.get("/products", tags=["商品"])
def list_products(keyword: Optional[str] = None, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        if keyword:
            rows = conn.execute(
                text("SELECT * FROM products WHERE name LIKE :kw OR country LIKE :kw ORDER BY sku_no"),
                {"kw": f"%{keyword}%"}
            ).mappings().all()
        else:
            rows = conn.execute(text("SELECT * FROM products ORDER BY sku_no")).mappings().all()
    return [dict(r) for r in rows]


@app.get("/products/{sku_no}", tags=["商品"])
def get_product(sku_no: int, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM products WHERE sku_no = :sku"), {"sku": sku_no}
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="SKU不存在")
    return dict(row)


# ------------------------------------------------------------------
# 進貨端點（僅限管理者，店員不可調整成本）
# ------------------------------------------------------------------
@app.post("/transactions/receive", tags=["進銷存"])
def api_receive_stock(req: ReceiveStockRequest, admin: dict = Depends(require_admin)):
    batch_id = fifo.receive_stock(
        sku_no=req.sku_no, qty_g=req.qty_kg * 1000,
        unit_cost_ntd_per_g=req.cost_ntd_per_100g / 100,
        receive_date=req.receive_date, supplier=req.supplier, lot_ref=req.lot_ref,
        store_id=req.store_id, created_by=admin.get("user_id")
    )
    return {"batch_id": batch_id, "message": "進貨登錄成功"}


# ------------------------------------------------------------------
# 出貨端點（店員與管理者皆可執行，此為店員日常主要操作）
# ------------------------------------------------------------------
@app.post("/transactions/issue", tags=["進銷存"])
def api_issue_stock(req: IssueStockRequest, user: dict = Depends(require_staff_or_admin)):
    try:
        txn = fifo.issue_stock(
            sku_no=req.sku_no, qty_g=req.qty_g,
            sell_price_ntd_per_g=req.sell_price_ntd_per_100g / 100,
            issue_date=req.issue_date, channel=req.channel, reference=req.reference,
            store_id=req.store_id, created_by=user.get("user_id")
        )
    except fifo.InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = {
        "txn_id": txn.txn_id, "qty_g": txn.qty_g,
        "total_amount_ntd": txn.total_amount_ntd,
        "allocations": [{"batch_id": a.batch_id, "qty_g": a.qty_g,
                          "unit_cost_ntd_per_g": a.unit_cost_ntd_per_g} for a in txn.allocations],
    }
    # 店員權限不顯示成本與毛利，僅管理者可見（呼應RBAC需求：店員僅可出貨，無法查看成本）
    if user.get("role") == "admin":
        result["total_cogs_ntd"] = txn.total_cogs_ntd
        result["gross_profit_ntd"] = txn.gross_profit_ntd
    return result


# ------------------------------------------------------------------
# 庫存查詢（店員與管理者皆可查詢數量，僅管理者看得到成本/市值）
# ------------------------------------------------------------------
@app.get("/inventory", tags=["庫存"])
def api_get_inventory(store_id: int = 1, user: dict = Depends(require_staff_or_admin)):
    positions = fifo.get_all_inventory_positions(store_id=store_id)
    is_admin = user.get("role") == "admin"
    return [
        {
            "sku_no": p.sku_no, "name": p.name, "total_qty_g": p.total_qty_g,
            "oldest_batch_date": p.oldest_batch_date, "oldest_batch_age_days": p.oldest_batch_age_days,
            "batch_count": p.batch_count,
            **({"total_value_ntd": p.total_value_ntd,
                "weighted_avg_cost_ntd_per_g": p.weighted_avg_cost_ntd_per_g} if is_admin else {})
        }
        for p in positions
    ]


@app.get("/inventory/aging-alerts", tags=["庫存"])
def api_aging_alerts(store_id: int = 1, user: dict = Depends(require_staff_or_admin)):
    return fifo.get_fifo_aging_alerts(store_id=store_id)


# ------------------------------------------------------------------
# 損益報表（僅限管理者）
# ------------------------------------------------------------------
@app.get("/reports/profit", tags=["報表"])
def api_profit_report(start_date: date, end_date: date, store_id: Optional[int] = None,
                        admin: dict = Depends(require_admin)):
    return fifo.get_profit_report(start_date.isoformat(), end_date.isoformat(), store_id=store_id)


@app.get("/reports/store-comparison", tags=["報表"])
def api_store_comparison(start_date: date, end_date: date, admin: dict = Depends(require_admin)):
    """多門店績效比較，僅限管理者（第二門店開幕後即可使用此報表）"""
    return fifo.get_store_comparison(start_date.isoformat(), end_date.isoformat())


@app.get("/", tags=["系統"])
def health_check():
    return {"status": "ok", "service": "A.O.M Cafe Inventory API", "version": "2.0.0"}
