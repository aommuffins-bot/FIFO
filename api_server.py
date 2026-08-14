"""
api_server.py — A.O.M Cafe 進銷存 API 唯一入口
整合：auth.py、db_engine.py、fifo_engine_v2.py、api_models.py
"""
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.http import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from datetime import datetime
from typing import Optional, List
import jwt
import hashlib
import os

# 匯入自定義模組
from db_engine import get_conn, products, batches, transactions, init_db
from auth import authenticate, encode_token
from fifo_engine_v2 import receive_stock as fifo_receive, issue_stock as fifo_issue, InsufficientStockError
from api_models import ReceiveRequest, IssueRequest, InventoryItem, BatchItem, TransactionItem, LoginResponse, SuccessResponse

app = FastAPI(title="A.O.M Cafe 進銷存 API", version="2.0.0", description="FIFO 進銷存系統線上版")

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aommuffins-bot.github.io",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化資料庫（自動建表）
init_db()

# JWT 設定
SECRET_KEY = os.environ.get("AOM_JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()

# ==================== 認證工具 ====================
async def get_current_user(token: str = Depends(security)):
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = authenticate(username, "")
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
@app.post("/auth/login", response_model=LoginResponse)
async def login(username: str = Query(...), password: str = Query(...)):
    user = authenticate(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = encode_token({
        "sub": user["username"],
        "role": user["role"],
        "store_id": user["store_id"]
    })
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        "store_id": user["store_id"]
    }

# ==================== 庫存端點 ====================
@app.get("/inventory", response_model=List[InventoryItem])
async def get_inventory(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT p.sku_no, p.name, 
                   COALESCE(SUM(b.qty_remaining_g), 0) as total_qty_g,
                   COUNT(b.batch_id) as batch_count
            FROM products p
            LEFT JOIN batches b ON p.sku_no = b.sku_no AND b.store_id = :store_id
            WHERE p.is_active = 1
            GROUP BY p.sku_no, p.name
            ORDER BY p.sku_no
        """), {"store_id": store_id}).mappings().all()
        
        return [
            {
                "sku_no": row["sku_no"],
                "name": row["name"],
                "total_qty_g": row["total_qty_g"],
                "batch_count": row["batch_count"],
                "oldest_batch_age_days": 30
            }
            for row in result
        ]

@app.get("/inventory/batches", response_model=List[BatchItem])
async def get_batches(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT b.batch_id, b.sku_no, b.receive_date, b.qty_remaining_g as qty_g,
                   b.unit_cost_ntd_per_g as cost_per_100g, b.supplier, b.origin, b.flavor, b.process,
                   p.name
            FROM batches b
            JOIN products p ON b.sku_no = p.sku_no
            WHERE b.store_id = :store_id AND b.qty_remaining_g > 0
            ORDER BY b.receive_date ASC, b.batch_id ASC
        """), {"store_id": store_id}).mappings().all()
        
        return [
            {
                "sku_no": row["sku_no"],
                "batch_id": row["batch_id"],
                "receive_date": row["receive_date"],
                "qty_g": row["qty_g"],
                "cost_per_100g": row["cost_per_100g"],
                "supplier": row["supplier"] or "",
                "origin": row["origin"] or "",
                "flavor": row["flavor"] or "",
                "process": row["process"] or "",
                "age_days": 30
            }
            for row in result
        ]

# ==================== 交易端點 ====================
@app.post("/transactions/receive", response_model=SuccessResponse)
async def receive_stock(req: ReceiveRequest, current_user: dict = Depends(get_current_user)):
    try:
        batch_id = fifo_receive(
            sku_no=req.sku_no,
            qty_g=req.qty_g,
            unit_cost_ntd_per_g=req.cost_per_100g / 100,
            supplier=req.supplier,
            origin=req.origin,
            flavor=req.flavor,
            process=req.process,
            receive_date=req.roast_date or datetime.utcnow().strftime("%Y-%m-%d"),
            store_id=current_user["store_id"],
            created_by=current_user.get("user_id")
        )
        
        return {
            "status": "success",
            "message": f"進貨成功：{req.qty_g}g",
            "new_total_qty_g": req.qty_g
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/transactions/issue", response_model=SuccessResponse)
async def issue_stock(req: IssueRequest, current_user: dict = Depends(get_current_user)):
    try:
        txn = fifo_issue(
            sku_no=req.sku_no,
            qty_g=req.qty_g,
            sell_price_ntd_per_100g=req.sell_price_ntd_per_100g / 100,
            channel=req.channel,
            store_id=current_user["store_id"],
            created_by=current_user.get("user_id")
        )
        
        return {
            "status": "success",
            "message": f"出貨成功：{req.qty_g}g",
            "batches_used": [{"batch_id": a.batch_id, "qty_used": a.qty_g} for a in txn.allocations],
            "remaining_total_qty_g": 0
        }
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/transactions", response_model=List[TransactionItem])
async def get_transactions(
    store_id: int = Query(...),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    with get_conn() as conn:
        query = """
            SELECT t.txn_id, t.sku_no, t.txn_type, t.txn_date, t.qty_g,
                   t.unit_price_ntd_per_g, t.total_amount_ntd, t.channel,
                   b.supplier, b.origin, b.flavor, b.process, t.created_at as timestamp
            FROM transactions t
            LEFT JOIN batches b ON t.sku_no = b.sku_no AND b.store_id = t.store_id
            WHERE t.store_id = :store_id
        """
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
        
        return [
            {
                "txn_id": row["txn_id"],
                "sku_no": row["sku_no"],
                "txn_type": row["txn_type"],
                "txn_date": row["txn_date"],
                "qty_g": row["qty_g"],
                "unit_price_ntd_per_g": row["unit_price_ntd_per_g"],
                "total_amount_ntd": row["total_amount_ntd"],
                "channel": row["channel"],
                "supplier": row["supplier"],
                "origin": row["origin"],
                "flavor": row["flavor"],
                "process": row["process"],
                "timestamp": row["timestamp"].isoformat() if row["timestamp"] else ""
            }
            for row in result
        ]

# ==================== 報表端點 ====================
@app.get("/reports/inventory")
async def export_inventory_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT p.sku_no, p.name, 
                   COALESCE(SUM(b.qty_remaining_g), 0) as total_qty_g,
                   COUNT(b.batch_id) as batch_count
            FROM products p
            LEFT JOIN batches b ON p.sku_no = b.sku_no AND b.store_id = :store_id
            WHERE p.is_active = 1
            GROUP BY p.sku_no, p.name
            ORDER BY p.sku_no
        """), {"store_id": store_id}).mappings().all()
        
        csv_content = "SKU,品名，庫存量 (g),批次數\n"
        for row in result:
            csv_content += f"{row['sku_no']},{row['name']},{row['total_qty_g']},{row['batch_count']}\n"
        
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventory_report.csv"}
        )

@app.get("/reports/transactions")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    with get_conn() as conn:
        result = conn.execute(text("""
            SELECT t.txn_type, t.txn_date, t.sku_no, t.qty_g,
                   t.unit_price_ntd_per_g, t.total_amount_ntd, t.channel,
                   b.supplier, b.origin, b.flavor, b.process
            FROM transactions t
            LEFT JOIN batches b ON t.sku_no = b.sku_no AND b.store_id = t.store_id
            WHERE t.store_id = :store_id
            ORDER BY t.txn_date DESC
        """), {"store_id": store_id}).mappings().all()
        
        csv_content = "日期，類型，SKU,數量 (g),單價，總額，通路/供應商，產區，風味，處理法\n"
        for row in result:
            date = row["txn_date"]
            unit_price = row["unit_price_ntd_per_g"] or 0
            counterparty = row["supplier"] or row["channel"] or ""
            csv_content += f"{date},{row['txn_type']},{row['sku_no']},{row['qty_g']},{unit_price},{row['total_amount_ntd']},{counterparty},{row['origin'] or ''},{row['flavor'] or ''},{row['process'] or ''}\n"
        
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions_report.csv"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))