"""
fifo_engine_v2.py -- 商業邏輯層 v2：支援多門店(store_id)的 FIFO 進銷存核心引擎
------------------------------------------------------------------------
核心 FIFO 演算法：
1. 進貨（receive_stock）：建立新批次，寫入 IN 交易紀錄
2. 出貨（issue_stock）：依 receive_date 由舊到新扣帳，寫入 OUT 交易紀錄與分攤明細
3. 所有函式皆支援 store_id，同店庫存互相獨立，不同店互不影響
"""

import datetime as _dt
from typing import List, Optional
from sqlalchemy import text
from db_engine import get_conn
from models import Transaction, AllocationLine, InventoryPosition


class InsufficientStockError(Exception):
    pass


# ------------------------------------------------------------------
# 進貨（IN）
# ------------------------------------------------------------------
def receive_stock(sku_no: int, qty_g: float, unit_cost_ntd_per_g: float,
                   receive_date: Optional[str] = None,
                   supplier: Optional[str] = None,
                   lot_ref: Optional[str] = None,
                   store_id: int = 1,
                   created_by: Optional[int] = None) -> int:
    """登錄一筆進貨，建立新批次，並寫入 IN 交易紀錄。回傳新建立的 batch_id。"""
    receive_date = receive_date or _dt.date.today().isoformat()
    with get_conn() as conn:
        result = conn.execute(
            text(
                "INSERT INTO batches "
                "(sku_no, store_id, receive_date, qty_received_g, qty_remaining_g, "
                "unit_cost_ntd_per_g, supplier, lot_ref, created_by) "
                "VALUES (:sku, :store, :rdate, :qty, :qty, :cost, :sup, :lot, :uid)"
            ),
            {
                "sku": sku_no, "store": store_id, "rdate": receive_date, "qty": qty_g,
                "cost": unit_cost_ntd_per_g, "sup": supplier, "lot": lot_ref, "uid": created_by
            }
        )
        batch_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]
        total_amount = qty_g * unit_cost_ntd_per_g
        ref_text = lot_ref or ("批次#" + str(batch_id))
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g, "
                "total_amount_ntd, reference, created_by) "
                "VALUES (:sku, :store, 'IN', :tdate, :qty, :price, :amt, :ref, :uid)"
            ),
            {
                "sku": sku_no, "store": store_id, "tdate": receive_date, "qty": qty_g,
                "price": unit_cost_ntd_per_g, "amt": total_amount,
                "ref": ref_text, "uid": created_by
            }
        )
        return batch_id


# ------------------------------------------------------------------
# 出貨（OUT，FIFO 核心）
# ------------------------------------------------------------------
def issue_stock(sku_no: int, qty_g: float, sell_price_ntd_per_g: float,
                 issue_date: Optional[str] = None,
                 channel: str = "零售",
                 reference: Optional[str] = None,
                 store_id: int = 1,
                 created_by: Optional[int] = None) -> Transaction:
    """依 FIFO 原則於指定門店範圍內出貨：優先消耗該門店最早進貨的批次。"""
    issue_date = issue_date or _dt.date.today().isoformat()

    with get_conn() as conn:
        batches = conn.execute(
            text(
                "SELECT batch_id, qty_remaining_g, unit_cost_ntd_per_g, receive_date "
                "FROM batches WHERE sku_no = :sku AND store_id = :store AND qty_remaining_g > 0 "
                "ORDER BY receive_date ASC, batch_id ASC"
            ),
            {"sku": sku_no, "store": store_id}
        ).mappings().all()

        available = sum(b["qty_remaining_g"] for b in batches)
        if available < qty_g:
            raise InsufficientStockError(
                "門店" + str(store_id) + " SKU " + str(sku_no) +
                " 庫存不足：需求 " + str(qty_g) + "g，現有 " + str(available) + "g"
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
            allocations.append(
                AllocationLine(
                    batch_id=b["batch_id"], qty_g=take,
                    unit_cost_ntd_per_g=b["unit_cost_ntd_per_g"]
                )
            )
            total_cogs += take * b["unit_cost_ntd_per_g"]
            remaining_to_fulfill -= take

        total_amount = qty_g * sell_price_ntd_per_g
        gross_profit = total_amount - total_cogs

        result = conn.execute(
            text(
                "INSERT INTO transactions "
                "(sku_no, store_id, txn_type, txn_date, qty_g, unit_price_ntd_per_g, "
                "total_amount_ntd, total_cogs_ntd, gross_profit_ntd, channel, reference, created_by) "
                "VALUES (:sku, :store, 'OUT', :tdate, :qty, :price, :amt, :cogs, :profit, "
                ":channel, :ref, :uid)"
            ),
            {
                "sku": sku_no, "store": store_id, "tdate": issue_date, "qty": qty_g,
                "price": sell_price_ntd_per_g, "amt": total_amount, "cogs": total_cogs,
                "profit": gross_profit, "channel": channel, "ref": reference, "uid": created_by
            }
        )
        txn_id = result.lastrowid if hasattr(result, "lastrowid") else result.inserted_primary_key[0]

        for a in allocations:
            conn.execute(
                text(
                    "INSERT INTO txn_allocations (txn_id, batch_id, qty_g, unit_cost_ntd_per_g) "
                    "VALUES (:txn, :bid, :qty, :cost)"
                ),
                {"txn": txn_id, "bid": a.batch_id, "qty": a.qty_g, "cost": a.unit_cost_ntd_per_g}
            )

        return Transaction(
            txn_id=txn_id, sku_no=sku_no, txn_type="OUT", txn_date=issue_date,
            qty_g=qty_g, unit_price_ntd_per_g=sell_price_ntd_per_g,
            total_amount_ntd=total_amount, total_cogs_ntd=total_cogs,
            gross_profit_ntd=gross_profit, channel=channel, reference=reference,
            allocations=allocations
        )


# ------------------------------------------------------------------
# 庫存查詢
# ------------------------------------------------------------------
def get_inventory_position(sku_no: int, store_id: int = 1) -> Optional[InventoryPosition]:
    with get_conn() as conn:
        prod = conn.execute(
            text("SELECT name FROM products WHERE sku_no = :sku"), {"sku": sku_no}
        ).mappings().first()
        if not prod:
            return None

        rows = conn.execute(
            text(
                "SELECT batch_id, receive_date, qty_remaining_g, unit_cost_ntd_per_g "
                "FROM batches WHERE sku_no = :sku AND store_id = :store AND qty_remaining_g > 0 "
                "ORDER BY receive_date ASC"
            ),
            {"sku": sku_no, "store": store_id}
        ).mappings().all()

        total_qty = sum(r["qty_remaining_g"] for r in rows)
        total_value = sum(r["qty_remaining_g"] * r["unit_cost_ntd_per_g"] for r in rows)
        avg_cost = total_value / total_qty if total_qty > 0 else 0.0
        oldest_date = rows[0]["receive_date"] if rows else None
        age_days = None
        if oldest_date:
            age_days = (_dt.date.today() - _dt.date.fromisoformat(oldest_date)).days

        return InventoryPosition(
            sku_no=sku_no, name=prod["name"], total_qty_g=total_qty,
            total_value_ntd=total_value, weighted_avg_cost_ntd_per_g=avg_cost,
            oldest_batch_date=oldest_date, oldest_batch_age_days=age_days,
            batch_count=len(rows)
        )


def get_all_inventory_positions(store_id: int = 1) -> List[InventoryPosition]:
    with get_conn() as conn:
        sku_rows = conn.execute(
            text(
                "SELECT DISTINCT sku_no FROM batches "
                "WHERE store_id = :store AND qty_remaining_g > 0"
            ),
            {"store": store_id}
        ).mappings().all()
        sku_list = [r["sku_no"] for r in sku_rows]
    positions = [get_inventory_position(s, store_id) for s in sku_list]
    positions = [p for p in positions if p is not None]
    positions.sort(key=lambda p: p.sku_no)
    return positions


def get_all_batches(store_id: int = 1) -> List[dict]:
    """回傳所有批次明細（含品名），供進貨報表使用。"""
    with get_conn() as conn:
        rows = conn.execute(
            text(
                "SELECT b.sku_no, p.name, b.batch_id, b.receive_date, "
                "b.qty_received_g, b.qty_remaining_g, b.unit_cost_ntd_per_g, b.supplier "
                "FROM batches b JOIN products p ON b.sku_no = p.sku_no "
                "WHERE b.store_id = :store "
                "ORDER BY b.sku_no ASC, b.receive_date ASC, b.batch_id ASC"
            ),
            {"store": store_id}
        ).mappings().all()
        return [dict(r) for r in rows]


def get_transactions(store_id: int = 1, start_date: Optional[str] = None,
                      end_date: Optional[str] = None, txn_type: Optional[str] = None) -> List[dict]:
    query = "SELECT * FROM transactions WHERE store_id = :store"
    params = {"store": store_id}
    if txn_type:
        query += " AND txn_type = :ttype"
        params["ttype"] = txn_type
    if start_date:
        query += " AND txn_date >= :sdate"
        params["sdate"] = start_date
    if end_date:
        query += " AND txn_date <= :edate"
        params["edate"] = end_date
    query += " ORDER BY txn_id ASC"
    with get_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        return [dict(r) for r in rows]