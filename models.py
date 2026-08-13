from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Batch:
    batch_id: Optional[int]
    sku_no: int
    receive_date: str
    qty_received_g: float
    qty_remaining_g: float
    unit_cost_ntd_per_g: float
    supplier: Optional[str] = None
    lot_ref: Optional[str] = None


@dataclass
class AllocationLine:
    batch_id: int
    qty_g: float
    unit_cost_ntd_per_g: float


@dataclass
class Transaction:
    txn_id: Optional[int]
    sku_no: int
    txn_type: str
    txn_date: str
    qty_g: float
    unit_price_ntd_per_g: Optional[float] = None
    total_amount_ntd: Optional[float] = None
    total_cogs_ntd: Optional[float] = None
    gross_profit_ntd: Optional[float] = None
    channel: Optional[str] = None
    reference: Optional[str] = None
    allocations: List[AllocationLine] = field(default_factory=list)


@dataclass
class InventoryPosition:
    sku_no: int
    name: str
    total_qty_g: float
    total_value_ntd: float
    weighted_avg_cost_ntd_per_g: float
    oldest_batch_date: Optional[str]
    oldest_batch_age_days: Optional[int]
    batch_count: int
