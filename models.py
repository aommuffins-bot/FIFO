"""
models.py — 資料模型（Pydantic，與前端欄位完全一致）
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# ==================== 請求模型（與前端 JSON payload 一致）====================
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

# ==================== 回應模型（與前端顯示一致）====================
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
    supplier: Optional[str] = None
    origin: Optional[str] = None
    flavor: Optional[str] = None
    process: Optional[str] = None
    timestamp: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    store_id: int

class SuccessResponse(BaseModel):
    status: str
    message: str
    batch: Optional[dict] = None
    new_total_qty_g: Optional[float] = None
    batches_used: Optional[List[dict]] = None
    remaining_total_qty_g: Optional[float] = None