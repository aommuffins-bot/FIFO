"""
fifo_engine_v2.py — 商業邏輯層 v2：支援多門店 (store_id) 的 FIFO 進銷存核心引擎
"""

import datetime as _dt
from typing import List, Optional
from sqlalchemy import text
from db_engine import get_conn
from models import Batch, Transaction, AllocationLine, InventoryPosition

class InsufficientStockError(Exception):
    pass

def receive_stock(sku_no: int, qty_g: float, unit_cost_ntd_per_g: float,
                  receive_date: Optional[str] = None,
                  supplier: Optional[str] = None,
                  lot_ref: Optional[str] = None,
                  origin: Optional[str] = None,
                  flavor: Optional[str] = None,
                  process: Optional[str] = None,
                  roast_date: Optional[str] = None,
                  store_id: int = 1,
                  created_by: Optional[int] = None) -> int:
    """登錄一筆進貨，建立新批次（batch），並寫入 IN 交易紀錄。回傳新建立的 batch_id。"""
    receive_date = receive_date or _dt.date.today().isoformat()
    with get_conn() as conn:
        result = conn.execute(
            text("""INSERT INTO batches
            (sku_no, store_id, receive_date, qty_received_g, qty_remaining_g,
             unit_cost_ntd_per_g, supplier, origin, flavor, process, lot_ref, created_by)
            VALUES (:sku, :store, :rdate, :qty, :qty, :cost, :sup, :origin, :flavor, :process, :lot, :uid)"""),
            {"sku": sku_no, "store": store_id, "rdate": receive_date, "qty": qty_g,
             "cost": unit_cost_ntd_per_g, "sup": supplier, "origin": origin, "flavor": flavor,
             "process": process, "lot": lot_ref, "uid": created_by}
        )
        batch_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]
        total_amount = qty_g * unit_cost_ntd_per_g
        conn.execute(
            text("""INSERT INTO transactions
            (sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g,
             total_amount_ntd, reference, created_by)
            VALUES (:sku, :store, 'IN', :tdate, :qty, :price, :amt, :ref, :uid)"""),
            {"sku": sku_no, "store": store_id, "tdate": receive_date, "qty": qty_g,
             "price": unit_cost_ntd_per_g, "amt": total_amount,
             "ref": lot_ref or f"批次#{batch_id}", "uid": created_by}
        )
        return batch_id

def issue_stock(sku_no: int, qty_g: float, sell_price_ntd_per_g: float,
                issue_date: Optional[str] = None,
                channel: str = "零售",
                reference: Optional[str] = None,
                store_id: int = 1,
                created_by: Optional[int] = None) -> Transaction:
    """依 FIFO 原則於「指定門店 (store_id) 範圍內」出貨。"""
    issue_date = issue_date or _dt.date.today().isoformat()

    with get_conn() as conn:
        batches = conn.execute(
            text("""SELECT batch_id, qty_remaining_g, unit_cost_ntd_per_g, receive_date
            FROM batches
            WHERE sku_no = :sku AND store_id = :store AND qty_remaining_g > 0
            ORDER BY receive_date ASC, batch_id ASC"""),
            {"sku": sku_no, "store": store_id}
        ).mappings().all()

        available = sum(b["qty_remaining_g"] for b in batches)
        if available < qty_g:
            raise InsufficientStockError(
                f"門店{store_id} SKU {sku_no} 庫存不足：需求 {qty_g}g，現有 {available}g"
            )

        remaining_to_fulfill = qty_g
        allocations: List[AllocationLine] = []
        total_cogs = 0.0

        for b in batches:
            if remaining_to_fulfill <= 0:
                break
            take = min(b["qty_remaining_g"], remaining_to_fulfill)
            new_remaining = b["qty_remaining_g"] - take
            conn.execute(
                text("UPDATE batches SET qty_remaining_g = :qty WHERE batch_id = :bid"),
                {"qty": new_remaining, "bid": b["batch_id"]}
            )
            allocations.append(AllocationLine(
                batch_id=b["batch_id"], qty_g=take, unit_cost_ntd_per_g=b["unit_cost_ntd_per_g"]
            ))
            total_cogs += take * b["unit_cost_ntd_per_g"]
            remaining_to_fulfill -= take

        total_amount = qty_g * sell_price_ntd_per_g
        gross_profit = total_amount - total_cogs

        result = conn.execute(
            text("""INSERT INTO transactions
            (sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g,
             total_amount_ntd, total_cogs_ntd, gross_profit_ntd, channel, reference, created_by)
            VALUES (:sku, :store, 'OUT', :tdate, :qty, :price, :amt, :cogs, :profit, :channel, :ref, :uid)"""),
            {"sku": sku_no, "store": store_id, "tdate": issue_date, "qty": qty_g,
             "price": sell_price_ntd_per_g, "amt": total_amount, "cogs": total_cogs,
             "profit": gross_profit, "channel": channel, "ref": reference, "uid": created_by}
        )
        txn_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]

        for a in allocations:
            conn.execute(
                text("""INSERT INTO txn_allocations (txn_id, batch_id, qty_g, unit_cost_ntd_per_g)
                VALUES (:txn, :bid, :qty, :cost)"""),
                {"txn": txn_id, "bid": a.batch_id, "qty": a.qty_g, "cost": a.unit_cost_ntd_per_g}
            )

        return Transaction(
            txn_id=txn_id, sku_no=sku_no, txn_type="OUT", txn_date=issue_date,
            qty_g=qty_g, unit_price_ntd_per_g=sell_price_ntd_per_g,
            total_amount_ntd=total_amount, total_cogs_ntd=total_cogs,
            gross_profit_ntd=gross_profit, channel=channel, reference=reference,
            allocations=allocations
        )

def get_inventory_position(sku_no: int, store_id: int = 1) -> InventoryPosition:
    """查詢指定 SKU 於指定門店的庫存部位。"""
    with get_conn() as conn:
        row = conn.execute(
            text("""SELECT p.name,
                    COALESCE(SUM(b.qty_remaining_g), 0) as total_qty_g,
                    COALESCE(SUM(b.qty_remaining_g * b.unit_cost_ntd_per_g), 0) as total_value,
                    MIN(b.receive_date) as oldest_date,
                    COUNT(b.batch_id) as batch_count
            FROM products p
            LEFT JOIN batches b ON p.sku_no = b.sku_no AND b.store_id = :store
            WHERE p.sku_no = :sku AND p.is_active = 1
            GROUP BY p.name"""),
            {"sku": sku_no, "store": store_id}
        ).mappings().first()

        if not row or row["total_qty_g"] == 0:
            return InventoryPosition(
                sku_no=sku_no, name="", total_qty_g=0, total_value_ntd=0,
                weighted_avg_cost_ntd_per_g=0, oldest_batch_date=None,
                oldest_batch_age_days=None, batch_count=0
            )

        weighted_avg = row["total_value"] / row["total_qty_g"] if row["total_qty_g"] > 0 else 0
        oldest_date = row["oldest_date"]
        age_days = (_dt.date.today() - _dt.date.fromisoformat(oldest_date)).days if oldest_date else None

        return InventoryPosition(
            sku_no=sku_no, name=row["name"], total_qty_g=row["total_qty_g"],
            total_value_ntd=row["total_value"], weighted_avg_cost_ntd_per_g=weighted_avg,
            oldest_batch_date=oldest_date, oldest_batch_age_days=age_days,
            batch_count=row["batch_count"]
        )