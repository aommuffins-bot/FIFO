from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.http import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt
import hashlib

app = FastAPI(title="A.O.M Cafe 進銷存 API", version="2.0.0", description="FIFO 進銷存系統線上版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aommuffins-bot.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

USERS_DB = {
    "admin": {"username": "admin", "password_hash": hashlib.sha256("admin123".encode()).hexdigest(), "role": "admin", "store_id": 1},
}
SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

INVENTORY_DB = {1: {"sku_no": 1, "name": "商品 A", "batches": [], "total_qty_g": 0.0}, 2: {"sku_no": 2, "name": "商品 B", "batches": [], "total_qty_g": 0.0}}
TRANSACTIONS_DB = []
security = HTTPBearer()

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

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(security)):
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None: raise HTTPException(status_code=401, detail="Invalid token")
        user = USERS_DB.get(username)
        if user is None: raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/")
async def root(): return {"message": "A.O.M Cafe 進銷存 API v2.0.0", "status": "online"}

@app.get("/health")
async def health_check(): return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/auth/login")
async def login(username: str = Query(...), password: str = Query(...)):
    user = USERS_DB.get(username)
    if not user: raise HTTPException(status_code=401, detail="Invalid credentials")
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != user["password_hash"]: raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user["username"], "role": user["role"]}, expires_delta=timedelta(minutes=60))
    return {"access_token": access_token, "token_type": "bearer", "role": user["role"], "store_id": user["store_id"]}

@app.get("/inventory")
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id: raise HTTPException(status_code=403, detail="Access denied")
    result = []
    for sku_no, item in INVENTORY_DB.items():
        result.append({"sku_no": sku_no, "name": item["name"], "total_qty_g": item["total_qty_g"], "batch_count": len(item["batches"]), "oldest_batch_age_days": 0 if not item["batches"] else 30})
    return result

@app.get("/inventory/batches")
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id: raise HTTPException(status_code=403, detail="Access denied")
    result = []
    for sku_no, item in INVENTORY_DB.items():
        for batch in item["batches"]:
            result.append({"sku_no": sku_no, "batch_id": batch.get("batch_id", "N/A"), "received_date": batch.get("received_date", ""), "qty_g": batch.get("qty_g", 0), "cost_per_100g": batch.get("cost_per_100g", 0), "supplier": batch.get("supplier", ""), "origin": batch.get("origin", ""), "flavor": batch.get("flavor", ""), "process": batch.get("process", ""), "age_days": 30})
    return result

@app.post("/transactions/receive")
async def receive_stock(req: ReceiveRequest, current_user: dict = Depends(get_current_user)):
    if req.sku_no not in INVENTORY_DB: raise HTTPException(status_code=400, detail="Invalid SKU")
    new_batch = {"batch_id": "BATCH-" + datetime.utcnow().strftime("%Y%m%d%H%M%S"), "received_date": datetime.utcnow().isoformat(), "qty_g": req.qty_g, "cost_per_100g": req.cost_per_100g, "supplier": req.supplier, "origin": req.origin, "flavor": req.flavor, "process": req.process, "roast_date": req.roast_date}
    INVENTORY_DB[req.sku_no]["batches"].append(new_batch)
    INVENTORY_DB[req.sku_no]["total_qty_g"] += req.qty_g
    TRANSACTIONS_DB.append({"type": "receive", "sku_no": req.sku_no, "qty_g": req.qty_g, "cost_per_100g": req.cost_per_100g, "total_amount": req.qty_g * req.cost_per_100g / 100, "supplier": req.supplier, "origin": req.origin, "flavor": req.flavor, "process": req.process, "timestamp": new_batch["received_date"], "store_id": current_user["store_id"]})
    return {"status": "success", "message": "進貨成功：" + str(req.qty_g) + "g", "batch": new_batch, "new_total_qty_g": INVENTORY_DB[req.sku_no]["total_qty_g"]}

@app.post("/transactions/issue")
async def issue_stock(req: IssueRequest, current_user: dict = Depends(get_current_user)):
    if req.sku_no not in INVENTORY_DB: raise HTTPException(status_code=400, detail="Invalid SKU")
    item = INVENTORY_DB[req.sku_no]
    if item["total_qty_g"] < req.qty_g: raise HTTPException(status_code=400, detail="庫存不足：目前 " + str(item["total_qty_g"]) + "g，需要 " + str(req.qty_g) + "g")
    remaining = req.qty_g
    batches_used = []
    for batch in item["batches"]:
        if remaining <= 0: break
        if batch["qty_g"] <= remaining:
            batches_used.append({"batch_id": batch["batch_id"], "qty_used": batch["qty_g"]})
            remaining -= batch["qty_g"]
            batch["qty_g"] = 0
        else:
            batches_used.append({"batch_id": batch["batch_id"], "qty_used": remaining})
            batch["qty_g"] -= remaining
            remaining = 0
    item["total_qty_g"] -= req.qty_g
    TRANSACTIONS_DB.append({"type": "issue", "sku_no": req.sku_no, "qty_g": req.qty_g, "sell_price_ntd_per_100g": req.sell_price_ntd_per_100g, "total_amount": req.qty_g * req.sell_price_ntd_per_100g / 100, "channel": req.channel, "timestamp": datetime.utcnow().isoformat(), "store_id": current_user["store_id"], "batches_used": batches_used})
    return {"status": "success", "message": "出貨成功：" + str(req.qty_g) + "g", "batches_used": batches_used, "remaining_total_qty_g": item["total_qty_g"]}

@app.get("/transactions")
async def get_transactions(store_id: int = Query(...), start_date: Optional[str] = None, end_date: Optional[str] = None, type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id: raise HTTPException(status_code=403, detail="Access denied")
    result = TRANSACTIONS_DB.copy()
    if type: result = [t for t in result if t["type"] == type]
    if start_date: result = [t for t in result if t["timestamp"] >= start_date]
    if end_date: result = [t for t in result if t["timestamp"] <= end_date]
    return result

@app.get("/reports/inventory")
async def export_inventory_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id: raise HTTPException(status_code=403, detail="Access denied")
    csv_content = "SKU,品名，庫存量 (g),批次數\n"
    for sku_no, item in INVENTORY_DB.items(): csv_content += str(sku_no) + "," + item["name"] + "," + str(item["total_qty_g"]) + "," + str(len(item["batches"])) + "\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})

@app.get("/reports/transactions")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id: raise HTTPException(status_code=403, detail="Access denied")
    csv_content = "日期，類型，SKU,數量 (g),單價，總額，通路/供應商，產區，風味，處理法\n"
    for t in TRANSACTIONS_DB:
        date = t["timestamp"].split("T")[0]
        unit_price = t.get("cost_per_100g") or t.get("sell_price_ntd_per_100g")
        counterparty = t.get("supplier") or t.get("channel")
        origin = t.get("origin", "")
        flavor = t.get("flavor", "")
        process = t.get("process", "")
        csv_content += date + "," + t["type"] + "," + str(t["sku_no"]) + "," + str(t["qty_g"]) + "," + str(unit_price) + "," + str(t["total_amount"]) + "," + str(counterparty) + "," + str(origin) + "," + str(flavor) + "," + str(process) + "\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions_report.csv"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)