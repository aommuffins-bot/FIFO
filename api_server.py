"""
api_server.py — A.O.M Cafe 進銷存 API（保證 /docs 能開啟版）
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
import secrets

# ==================== FastAPI 應用 ====================
app = FastAPI(
    title="A.O.M Cafe 進銷存 API",
    version="2.0.0",
    description="FIFO 進銷存系統線上版",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aommuffins-bot.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT 設定
SECRET_KEY = os.environ.get("AOM_JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
security = HTTPBearer()

# 記憶體儲存（保證能運作，不依賴資料庫）
USERS_DB = {
    "admin": {"user_id": 1, "username": "admin", "password_hash": hashlib.pbkdf2_hmac("sha256", "admin123".encode(), "salt123".encode(), 100000).hex(), "password_salt": "salt123", "role": "admin", "store_id": 1, "is_active": 1},
    "aom_founder": {"user_id": 2, "username": "aom_founder", "password_hash": hashlib.pbkdf2_hmac("sha256", "Dc20220111".encode(), "salt456".encode(), 100000).hex(), "password_salt": "salt456", "role": "admin", "store_id": 1, "is_active": 1},
}

INVENTORY_DB = {
    1: {"sku_no": 1, "name": "耶加雪菲 Yirgacheffe G1", "batches": [], "total_qty_g": 0.0},
    2: {"sku_no": 2, "name": "肯亞 AA 水洗", "batches": [], "total_qty_g": 0.0},
    3: {"sku_no": 3, "name": "哥倫比亞 Huila Supremo", "batches": [], "total_qty_g": 0.0},
    4: {"sku_no": 4, "name": "蘇門達臘 Mandheling G1", "batches": [], "total_qty_g": 0.0},
    5: {"sku_no": 5, "name": "耶加雪菲 日曬 G1", "batches": [], "total_qty_g": 0.0},
}

TRANSACTIONS_DB = []

# ==================== Pydantic 模型 ====================
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

# ==================== 工具函式 ====================
def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()

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
        user = USERS_DB.get(username)
        if not user or not user["is_active"]:
            raise HTTPException(status_code=401, detail="User not found")
        return user
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
    user = USERS_DB.get(username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    pw_hash = hash_password(password, user["password_salt"])
    if pw_hash != user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token({"sub": user["username"], "role": user["role"], "store_id": user["store_id"]})
    return {"access_token": access_token, "token_type": "bearer", "role": user["role"], "store_id": user["store_id"]}

@app.get("/inventory", response_model=List[InventoryItem])
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    result = []
    for sku_no, item in INVENTORY_DB.items():
        result.append({
            "sku_no": sku_no,
            "name": item["name"],
            "total_qty_g": item["total_qty_g"],
            "batch_count": len(item["batches"])
        })
    return result

@app.get("/inventory/batches", response_model=List[BatchItem])
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    result = []
    for sku_no, item in INVENTORY_DB.items():
        for batch in item["batches"]:
            result.append({
                "sku_no": sku_no,
                "batch_id": batch["batch_id"],
                "receive_date": batch["receive_date"],
                "qty_g": batch["qty_g"],
                "cost_per_100g": batch["cost_per_100g"],
                "supplier": batch.get("supplier", ""),
                "origin": batch.get("origin", ""),
                "flavor": batch.get("flavor", ""),
                "process": batch.get("process", "")
            })
    return result

@app.post("/transactions/receive", response_model=SuccessResponse)
async def receive_stock(req: ReceiveRequest, current_user: dict = Depends(get_current_user)):
    try:
        receive_date = datetime.utcnow().strftime("%Y-%m-%d")
        batch_id = len(INVENTORY_DB[req.sku_no]["batches"]) + 1
        new_batch = {
            "batch_id": batch_id,
            "receive_date": receive_date,
            "qty_g": req.qty_g,
            "cost_per_100g": req.cost_per_100g,
            "supplier": req.supplier,
            "origin": req.origin,
            "flavor": req.flavor,
            "process": req.process
        }
        INVENTORY_DB[req.sku_no]["batches"].append(new_batch)
        INVENTORY_DB[req.sku_no]["total_qty_g"] += req.qty_g
        
        TRANSACTIONS_DB.append({
            "txn_id": len(TRANSACTIONS_DB) + 1,
            "sku_no": req.sku_no,
            "txn_type": "IN",
            "txn_date": receive_date,
            "qty_g": req.qty_g,
            "unit_price_ntd_per_g": req.cost_per_100g / 100,
            "total_amount_ntd": req.qty_g * req.cost_per_100g / 100,
            "channel": "進貨",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {"status": "success", "message": f"進貨成功：{req.qty_g}g", "new_total_qty_g": INVENTORY_DB[req.sku_no]["total_qty_g"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/transactions/issue", response_model=SuccessResponse)
async def issue_stock(req: IssueRequest, current_user: dict = Depends(get_current_user)):
    try:
        issue_date = datetime.utcnow().strftime("%Y-%m-%d")
        item = INVENTORY_DB.get(req.sku_no)
        if not item:
            raise HTTPException(status_code=400, detail="Invalid SKU")
        if item["total_qty_g"] < req.qty_g:
            raise HTTPException(status_code=400, detail=f"庫存不足：目前 {item['total_qty_g']}g，需要 {req.qty_g}g")
        
        remaining = req.qty_g
        batches_used = []
        total_cogs = 0.0
        
        for batch in item["batches"]:
            if remaining <= 0:
                break
            take = min(batch["qty_g"], remaining)
            batch["qty_g"] -= take
            remaining -= take
            batches_used.append({"batch_id": batch["batch_id"], "qty_used": take})
            total_cogs += take * batch["cost_per_100g"] / 100
        
        item["total_qty_g"] -= req.qty_g
        
        total_amount = req.qty_g * req.sell_price_ntd_per_100g / 100
        
        TRANSACTIONS_DB.append({
            "txn_id": len(TRANSACTIONS_DB) + 1,
            "sku_no": req.sku_no,
            "txn_type": "OUT",
            "txn_date": issue_date,
            "qty_g": req.qty_g,
            "unit_price_ntd_per_g": req.sell_price_ntd_per_100g / 100,
            "total_amount_ntd": total_amount,
            "channel": req.channel,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {"status": "success", "message": f"出貨成功：{req.qty_g}g", "batches_used": batches_used, "new_total_qty_g": item["total_qty_g"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/transactions", response_model=List[TransactionItem])
async def get_transactions(store_id: int = Query(...), start_date: Optional[str] = None, end_date: Optional[str] = None, type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    result = TRANSACTIONS_DB.copy()
    if type:
        result = [t for t in result if t["txn_type"] == type]
    if start_date:
        result = [t for t in result if t["txn_date"] >= start_date]
    if end_date:
        result = [t for t in result if t["txn_date"] <= end_date]
    return result

@app.get("/reports/inventory")
async def export_inventory_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    csv_content = "SKU,品名，庫存量 (g),批次數\n"
    for sku_no, item in INVENTORY_DB.items():
        csv_content += f"{sku_no},{item['name']},{item['total_qty_g']},{len(item['batches'])}\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})

@app.get("/reports/transactions")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    csv_content = "日期，類型，SKU,數量 (g),單價，總額，通路\n"
    for t in TRANSACTIONS_DB:
        csv_content += f"{t['txn_date']},{t['txn_type']},{t['sku_no']},{t['qty_g']},{t['unit_price_ntd_per_g']},{t['total_amount_ntd']},{t['channel']}\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions_report.csv"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
