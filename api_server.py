"""
api_server.py -- A.O.M Café FIFO API v9
------------------------------------------------------------------------
本版本基於 v8（角色權限限制版），新增啟動時自動執行資料庫遷移：
- migrate_add_unique_natural_key.migrate()：為 products 表的
  (continent, country, name) 組合建立唯一索引，防止未來因命名疏失
  產生重複商品，確保 seed_135sku.py 的自然鍵比對邏輯永遠準確無歧義。

啟動流程順序（重要，不可調換）：
1. db_engine.init_db()              -- 建立資料表
2. seed_135sku.seed()               -- 寫入/更新135筆商品主檔（自然鍵比對）
3. migrate_add_unique_natural_key.migrate()  -- 確認無重複後建立唯一索引
4. auth.seed_known_accounts()       -- 確保 admin/aom_founder/aom_staff 帳號存在

其餘架構與 v8 相同：
- aom_founder, admin（管理者）：可進貨、可出貨、可查看完整報表
- staff（店員）：僅可執行出貨，進貨與報表端點回傳 403 Forbidden
- 進貨/出貨/庫存查詢皆呼叫 fifo_engine_v2.py 的 FIFO 引擎，寫入真實資料庫
- 登入機制使用 auth.py 的 PBKDF2 + 自製 JWT（HS256）
"""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Depends, HTTPException, Query, Form
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import os

logger = logging.getLogger("uvicorn.error")

import db_engine
import auth
import fifo_engine_v2 as fifo
import seed_135sku
import migrate_add_unique_natural_key
from sqlalchemy import text as _sql_text

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db_engine.init_db()
        seed_135sku.seed()
        migrate_add_unique_natural_key.migrate()
        auth.seed_known_accounts()
        logger.info("Startup: database initialized, 135 SKU seeded, "
                    "unique natural-key index ensured, accounts ensured.")
    except Exception as e:
        logger.warning("Startup: database initialization failed (%s). "
                        "The service is still running, but /inventory, /transactions, "
                        "/products and related endpoints will fail until this is fixed.", e)
    yield


app = FastAPI(
    title="A.O.M Café FIFO API",
    version="9.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aommuffins-bot.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    store_id: int


class ReceiveRequest(BaseModel):
    sku_no: int
    qty_g: float
    cost_per_100g: float
    supplier: str
    origin: Optional[str] = ""
    flavor: Optional[str] = ""
    process: Optional[str] = ""


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


class ProductItem(BaseModel):
    sku_no: int
    name: str
    continent: str
    country: str
    process: str
    variety: str
    flavor: str
    rating: str


class SuccessResponse(BaseModel):
    status: str
    message: str
    new_total_qty_g: Optional[float] = None


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = auth.decode_token(token)
    except auth.TokenError as e:
        raise HTTPException(status_code=401, detail=str(e), headers={"WWW-Authenticate": "Bearer"})
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    return payload


def require_admin(current_user: dict = Depends(get_current_user)):
    """
    權限守衛：僅允許 role == "admin" 的使用者通過。
    掛在需要管理者權限的端點上（例如進貨 /transactions/receive），
    店員(staff)呼叫時會收到 403 Forbidden。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="權限不足：僅管理者(admin)可執行此操作，店員(staff)僅可執行出貨"
        )
    return current_user


@app.get("/")
async def root():
    return {"message": "A.O.M Café 進銷存 API v9.0.0", "status": "online"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/auth/login", response_model=Token, summary="使用者登入")
async def login_for_access_token(
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    form_username: Optional[str] = Form(None, alias="username"),
    form_password: Optional[str] = Form(None, alias="password")
):
    if form_username and form_password:
        username = form_username
        password = form_password
    elif not username or not password:
        raise HTTPException(status_code=400, detail="請提供 username 和 password",
                             headers={"WWW-Authenticate": "Bearer"})

    try:
        user = auth.authenticate(username, password)
    except Exception as e:
        raise HTTPException(status_code=500, detail="資料庫尚未就緒：" + str(e))

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials",
                             headers={"WWW-Authenticate": "Bearer"})

    access_token = auth.encode_token({
        "sub": user["username"], "role": user["role"], "store_id": user["store_id"],
        "user_id": user["user_id"]
    })
    return {
        "access_token": access_token, "token_type": "bearer",
        "role": user["role"], "store_id": user["store_id"]
    }


@app.get("/products", response_model=List[ProductItem], summary="取得所有商品資料")
async def get_products():
    try:
        with db_engine.get_conn() as conn:
            rows = conn.execute(
                _sql_text(
                    "SELECT sku_no, name, continent, country, process, variety, flavor, rating "
                    "FROM products ORDER BY sku_no ASC"
                )
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail="無法讀取商品主檔：" + str(e))


@app.get("/inventory", response_model=List[InventoryItem], summary="取得即時庫存彙總")
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        positions = fifo.get_all_inventory_positions(store_id=store_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="庫存查詢失敗：" + str(e))
    return [
        {
            "sku_no": p.sku_no, "name": p.name,
            "total_qty_g": p.total_qty_g, "batch_count": p.batch_count
        }
        for p in positions
    ]


@app.get("/inventory/batches", summary="取得所有批次明細")
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        rows = fifo.get_all_batches(store_id=store_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="批次查詢失敗：" + str(e))
    result = []
    for r in rows:
        issued = r["qty_received_g"] - r["qty_remaining_g"]
        result.append({
            "sku_no": r["sku_no"], "name": r["name"], "batch_id": r["batch_id"],
            "receive_date": r["receive_date"],
            "received_qty_g": r["qty_received_g"],
            "issued_qty_g": issued,
            "remaining_qty_g": r["qty_remaining_g"],
            "cost_per_100g": r["unit_cost_ntd_per_g"] * 100,
            "supplier": r["supplier"] or ""
        })
    return result


@app.post("/transactions/receive", response_model=SuccessResponse, summary="進貨登錄（限管理者 admin）")
async def receive_stock(req: ReceiveRequest, current_user: dict = Depends(require_admin)):
    try:
        fifo.receive_stock(
            sku_no=req.sku_no,
            qty_g=req.qty_g,
            unit_cost_ntd_per_g=req.cost_per_100g / 100,
            supplier=req.supplier,
            lot_ref=req.origin or None,
            store_id=current_user["store_id"],
            created_by=current_user.get("user_id")
        )
        position = fifo.get_inventory_position(req.sku_no, store_id=current_user["store_id"])
        new_total = position.total_qty_g if position else req.qty_g
        return {"status": "success", "message": "進貨成功：" + str(req.qty_g) + "g",
                "new_total_qty_g": new_total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/transactions/issue", response_model=SuccessResponse, summary="出貨登錄（admin/staff皆可）")
async def issue_stock(req: IssueRequest, current_user: dict = Depends(get_current_user)):
    try:
        fifo.issue_stock(
            sku_no=req.sku_no,
            qty_g=req.qty_g,
            sell_price_ntd_per_g=req.sell_price_ntd_per_100g / 100,
            channel=req.channel,
            store_id=current_user["store_id"],
            created_by=current_user.get("user_id")
        )
        position = fifo.get_inventory_position(req.sku_no, store_id=current_user["store_id"])
        new_total = position.total_qty_g if position else 0.0
        return {"status": "success", "message": "出貨成功：" + str(req.qty_g) + "g",
                "new_total_qty_g": new_total}
    except fifo.InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/transactions", summary="查詢交易明細")
async def list_transactions(store_id: int = Query(...), start_date: Optional[str] = None,
                             end_date: Optional[str] = None, type: Optional[str] = None,
                             current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        rows = fifo.get_transactions(store_id=store_id, start_date=start_date,
                                      end_date=end_date, txn_type=type)
    except Exception as e:
        raise HTTPException(status_code=500, detail="交易查詢失敗：" + str(e))
    return rows


@app.get("/reports/inventory", summary="匯出進貨報表（限管理者 aom_founder, admin）")
async def export_inventory_report(store_id: int = Query(...), current_user: dict = Depends(require_admin)):
    """
    進貨報表欄位：SKU, 品名, 進貨日期, 供應商, 當批次進貨價(NT$/100g),
    進貨量(g), 出庫量(g), 剩餘庫存量(g)
    僅管理者可查看（涉及成本資訊，店員不可查看）。
    """
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        rows = fifo.get_all_batches(store_id=store_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="報表產生失敗：" + str(e))
    csv_content = "SKU,品名,進貨日期,供應商,當批次進貨價(NT$/100g),進貨量(g),出庫量(g),剩餘庫存量(g)\n"
    for r in rows:
        issued = r["qty_received_g"] - r["qty_remaining_g"]
        csv_content += str(r["sku_no"]) + "," + r["name"] + "," + r["receive_date"] + "," + \
            str(r["supplier"] or "") + "," + str(r["unit_cost_ntd_per_g"] * 100) + "," + \
            str(r["qty_received_g"]) + "," + str(issued) + "," + str(r["qty_remaining_g"]) + "\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})


@app.get("/reports/transactions", summary="匯出出貨報表（限管理者 aom_founder, admin，僅 OUT 類型交易）")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(require_admin)):
    """
    出貨報表欄位：日期, SKU, 數量(g), 單價(NT$/g), 總額, 通路（僅顯示 OUT 出貨交易）
    僅管理者可查看（涉及損益資訊，店員不可查看完整報表）。
    """
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        rows = fifo.get_transactions(store_id=store_id, txn_type="OUT")
    except Exception as e:
        raise HTTPException(status_code=500, detail="報表產生失敗：" + str(e))
    csv_content = "日期,SKU,數量(g),單價(NT$/g),總額,通路\n"
    for t in rows:
        csv_content += str(t["txn_date"]) + "," + str(t["sku_no"]) + "," + str(t["qty_g"]) + "," + \
            str(t["unit_price_ntd_per_g"]) + "," + str(t["total_amount_ntd"]) + "," + \
            str(t["channel"] or "") + "\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=transactions_report.csv"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
