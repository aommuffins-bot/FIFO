# A.O.M Cafe 進銷存 API 伺服器
# FastAPI 應用 - 包含 CORS 設定

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security.http import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import hashlib

# ==================== 應用程式初始化 ====================
app = FastAPI(
    title="A.O.M Cafe 進銷存 API",
    version="2.0.0",
    description="FIFO 進銷存系統線上版（橋接自離線版 fifo_engine.py）"
)

# ==================== CORS 設定（必須在所有路由之前）====================
# 根據 FastAPI 官方文件：https://fastapi.tiangolo.com/tutorial/cors/
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aommuffins-bot.github.io",  # GitHub Pages 正式環境
        "http://localhost:8000",  # 本機測試
        "http://127.0.0.1:8000",  # 本機測試
    ],
    allow_credentials=True,  # 允許攜帶 Cookie 和認證標頭
    allow_methods=["*"],  # 允許所有 HTTP 方法（GET, POST, PUT, DELETE, OPTIONS）
    allow_headers=["*"],  # 允許所有 HTTP 標頭
)

# ==================== 模擬資料庫（請替換為您的實際資料庫）====================
# 這裡使用簡化的記憶體儲存，實際部署時請替換為 SQLite/PostgreSQL

# 使用者資料
USERS_DB = {
    "admin": {
        "username": "admin",
        "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
        "role": "admin",
        "store_id": 1
    },
    "user1": {
        "username": "user1",
        "password_hash": hashlib.sha256("password123".encode()).hexdigest(),
        "role": "user",
        "store_id": 1
    }
}

# JWT 設定
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 模擬庫存資料
INVENTORY_DB = {
    1: {"sku_no": 1, "name": "商品 A", "batches": [], "total_qty_g": 0},
    2: {"sku_no": 2, "name": "商品 B", "batches": [], "total_qty_g": 0},
}

# 模擬交易記錄
TRANSACTIONS_DB = []

# ==================== 認證工具 ====================
security = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(security)):
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = USERS_DB.get(username)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== 系統端點 ====================
@app.get("/")
async def root():
    return {"message": "A.O.M Cafe 進銷存 API v2.0.0", "status": "online"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ==================== 認證端點 ====================
@app.post("/auth/login")
async def login(username: str = Query(...), password: str = Query(...)):
    """使用者登入，取得 JWT access token"""
    user = USERS_DB.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(
        data={"sub": user["username"], "role": user["role"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        "store_id": user["store_id"]
    }

# ==================== 庫存端點 ====================
@app.get("/inventory")
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """取得即時庫存汇总（FIFO）"""
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = []
    for sku_no, item in INVENTORY_DB.items():
        result.append({
            "sku_no": sku_no,
            "name": item["name"],
            "total_qty_g": item["total_qty_g"],
            "batch_count": len(item["batches"]),
            "oldest_batch_age_days": 0 if not item["batches"] else 30  # 簡化
        })

    return result

@app.get("/inventory/batches")
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """取得所有批次明細（FIFO 順序）"""
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = []
    for sku_no, item in INVENTORY_DB.items():
        for batch in item["batches"]:
            result.append({
                "sku_no": sku_no,
                "batch_id": batch.get("batch_id", "N/A"),
                "received_date": batch.get("received_date", ""),
                "qty_g": batch.get("qty_g", 0),
                "cost_per_100g": batch.get("cost_per_100g", 0),
                "age_days": 30  # 簡化
            })

    return result

# ==================== 交易端點 ====================
@app.post("/transactions/receive")
async def receive_stock(
    sku_no: int,
    qty_g: float,
    cost_per_100g: float,
    supplier: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """進貨登錄（FIFO 自動入帳）"""
    if sku_no not in INVENTORY_DB:
        raise HTTPException(status_code=400, detail="Invalid SKU")

    # 建立新批次
    new_batch = {
        "batch_id": f"BATCH-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "received_date": datetime.utcnow().isoformat(),
        "qty_g": qty_g,
        "cost_per_100g": cost_per_100g,
        "supplier": supplier
    }

    INVENTORY_DB[sku_no]["batches"].append(new_batch)
    INVENTORY_DB[sku_no]["total_qty_g"] += qty_g

    # 記錄交易
    TRANSACTIONS_DB.append({
        "type": "receive",
        "sku_no": sku_no,
        "qty_g": qty_g,
        "cost_per_100g": cost_per_100g,
        "total_amount": qty_g * cost_per_100g / 100,
        "supplier": supplier,
        "timestamp": new_batch["received_date"],
        "store_id": current_user["store_id"]
    })

    return {
        "status": "success",
        "message": f"進貨成功：{qty_g}g",
        "batch": new_batch,
        "new_total_qty_g": INVENTORY_DB[sku_no]["total_qty_g"]
    }

@app.post("/transactions/issue")
async def issue_stock(
    sku_no: int,
    qty_g: float,
    sell_price_ntd_per_100g: float,
    channel: str = "零售",
    current_user: dict = Depends(get_current_user)
):
    """出貨登錄（FIFO 自動扣帳）"""
    if sku_no not in INVENTORY_DB:
        raise HTTPException(status_code=400, detail="Invalid SKU")

    item = INVENTORY_DB[sku_no]
    if item["total_qty_g"] < qty_g:
        raise HTTPException(
            status_code=400,
            detail=f"庫存不足：目前 {item['total_qty_g']}g，需要 {qty_g}g"
        )

    # FIFO 扣帳邏輯
    remaining_to_issue = qty_g
    batches_used = []

    for batch in item["batches"]:
        if remaining_to_issue <= 0:
            break

        if batch["qty_g"] <= remaining_to_issue:
            # 整個批次用完
            batches_used.append({
                "batch_id": batch["batch_id"],
                "qty_used": batch["qty_g"]
            })
            remaining_to_issue -= batch["qty_g"]
            batch["qty_g"] = 0
        else:
            # 部分使用
            batches_used.append({
                "batch_id": batch["batch_id"],
                "qty_used": remaining_to_issue
            })
            batch["qty_g"] -= remaining_to_issue
            remaining_to_issue = 0

    # 更新總庫存量
    item["total_qty_g"] -= qty_g

    # 記錄交易
    TRANSACTIONS_DB.append({
        "type": "issue",
        "sku_no": sku_no,
        "qty_g": qty_g,
        "sell_price_ntd_per_100g": sell_price_ntd_per_100g,
        "total_amount": qty_g * sell_price_ntd_per_100g / 100,
        "channel": channel,
        "timestamp": datetime.utcnow().isoformat(),
        "store_id": current_user["store_id"],
        "batches_used": batches_used
    })

    return {
        "status": "success",
        "message": f"出貨成功：{qty_g}g",
        "batches_used": batches_used,
        "remaining_total_qty_g": item["total_qty_g"]
    }

@app.get("/transactions")
async def get_transactions(
    store_id: int = Query(...),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """查詢交易明細"""
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = TRANSACTIONS_DB.copy()

    if type:
        result = [t for t in result if t["type"] == type]

    if start_date:
        result = [t for t in result if t["timestamp"] >= start_date]

    if end_date:
        result = [t for t in result if t["timestamp"] <= end_date]

    return result

# ==================== 報表端點 ====================
@app.get("/reports/inventory")
async def export_inventory_report(
    store_id: int = Query(...),
    current_user: dict = Depends(get_current_user)
):
    """匯出庫存報表（CSV 格式）"""
    from fastapi.responses import PlainTextResponse

    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    csv_content = "SKU,品名，庫存量 (g),批次數\n"
    for sku_no, item in INVENTORY_DB.items():
        csv_content += f"{sku_no},{item['name']},{item['total_qty_g']},{len(item['batches'])}\n"

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory_report.csv"}
    )

@app.get("/reports/transactions")
async def export_transactions_report(
    store_id: int = Query(...),
    current_user: dict = Depends(get_current_user)
):
    """匯出交易報表（CSV 格式）"""
    from fastapi.responses import PlainTextResponse

    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")

    csv_content = "日期，類型，SKU,數量 (g),單價，總額，通路/供應商\n"
    for t in TRANS
