"""
fifo_engine_v2.py -- 商業邏輯層 v2：支援多門店(store_id)的FIFO進銷存核心引擎
------------------------------------------------------------------------
此檔案是離線版 fifo_engine.py 的線上化演進版本，核心FIFO演算法完全相同，
差異僅在於：
  1. 底層改用 db_engine.py（SQLAlchemy Core，可切換SQLite/PostgreSQL）
  2. 所有函式新增 store_id 參數（預設=1，與離線單店模式相容）
  3. 新增 created_by 參數，記錄操作人員（呼應RBAC需求）

★ 向下相容保證 ★
若僅有單一門店（store_id永遠=1），本模組行為與離線版fifo_engine.py完全一致，
CLI版本可直接改為 import fifo_engine_v2 as fifo 即可無痛切換至SQLAlchemy底層，
不影響任何既有操作流程。
"""

import datetime as _dt
from typing import List, Optional
from sqlalchemy import text
from db_engine import get_conn
from models import Batch, Transaction, AllocationLine, InventoryPosition


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
    """登錄一筆進貨，建立新批次（batch），並寫入IN交易紀錄。回傳新建立的 batch_id。"""
    receive_date = receive_date or _dt.date.today().isoformat()
    with get_conn() as conn:
        result = conn.execute(
            text("""INSERT INTO batches
                     (sku_no, store_id, receive_date, qty_received_g, qty_remaining_g,
                      unit_cost_ntd_per_g, supplier, lot_ref, created_by)
                     VALUES (:sku, :store, :rdate, :qty, :qty, :cost, :sup, :lot, :uid)"""),
            {"sku": sku_no, "store": store_id, "rdate": receive_date, "qty": qty_g,
             "cost": unit_cost_ntd_per_g, "sup": supplier, "lot": lot_ref, "uid": created_by}
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


# ------------------------------------------------------------------
# 出貨（OUT，FIFO核心，依store_id範圍內扣帳）
# ------------------------------------------------------------------
def issue_stock(sku_no: int, qty_g: float, sell_price_ntd_per_g: float,
                 issue_date: Optional[str] = None,
                 channel: str = "零售",
                 reference: Optional[str] = None,
                 store_id: int = 1,
                 created_by: Optional[int] = None) -> Transaction:
    """
    依FIFO原則於「指定門店(store_id)範圍內」出貨：優先消耗該門店最早進貨的批次。
    不同門店的庫存互相獨立，不會跨店互相扣抵（呼應第二門店擴張後的獨立庫存管理需求）。
    """
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
                     VALUES (:sku, :store, 'OUT', :tdate, :qty, :price, :amt, :cogs, :profit,
                             :channel, :ref, :uid)"""),
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


# ------------------------------------------------------------------
# 庫存查詢（依門店範圍）
# ------------------------------------------------------------------
def get_inventory_position(sku_no: int, store_id: int = 1) -> Optional[InventoryPosition]:
    with get_conn() as conn:
        prod = conn.execute(
            text("SELECT name FROM products WHERE sku_no = :sku"), {"sku": sku_no}
        ).mappings().first()
        if not prod:
            return None

        rows = conn.execute(
            text("""SELECT batch_id, receive_date, qty_remaining_g, unit_cost_ntd_per_g
                    FROM batches WHERE sku_no = :sku AND store_id = :store AND qty_remaining_g > 0
                    ORDER BY receive_date ASC"""),
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
        sku_list = [r["sku_no"] for r in conn.execute(
            text("SELECT DISTINCT sku_no FROM batches WHERE store_id = :store AND qty_remaining_g > 0"),
            {"store": store_id}
        ).mappings().all()]
    positions = [get_inventory_position(s, store_id) for s in sku_list]
    positions = [p for p in positions if p is not None]
    positions.sort(key=lambda p: (p.oldest_batch_age_days or 0), reverse=True)
    return positions


def get_fifo_aging_alerts(store_id: int = 1, shelf_life_months: int = 9,
                           warn_ratio: float = 0.8) -> List[dict]:
    warn_days = int(shelf_life_months * 30.4 * warn_ratio)
    expire_days = int(shelf_life_months * 30.4)
    today = _dt.date.today()
    alerts = []
    with get_conn() as conn:
        rows = conn.execute(
            text("""SELECT b.batch_id, b.sku_no, p.name, b.receive_date,
                           b.qty_remaining_g, b.unit_cost_ntd_per_g
                    FROM batches b JOIN products p ON b.sku_no = p.sku_no
                    WHERE b.store_id = :store AND b.qty_remaining_g > 0
                    ORDER BY b.receive_date ASC"""),
            {"store": store_id}
        ).mappings().all()
    for r in rows:
        age = (today - _dt.date.fromisoformat(r["receive_date"])).days
        if age >= warn_days:
            alerts.append({
                "batch_id": r["batch_id"], "sku_no": r["sku_no"], "name": r["name"],
                "receive_date": r["receive_date"], "age_days": age,
                "qty_remaining_g": r["qty_remaining_g"],
                "status": "已超期" if age >= expire_days else "即將超期",
            })
    return alerts


# ------------------------------------------------------------------
# 損益報表（可跨店彙總或指定單店）
# ------------------------------------------------------------------
def get_profit_report(start_date: str, end_date: str, store_id: Optional[int] = None) -> dict:
    """
    依日期區間統計營收/COGS/毛利，依通路拆分。
    store_id=None 時彙總所有門店；指定store_id則僅統計該門店（供管理者比較各店績效）。
    """
    query = """SELECT channel, SUM(total_amount_ntd) as revenue,
                      SUM(total_cogs_ntd) as cogs, SUM(gross_profit_ntd) as profit,
                      SUM(qty_g) as qty_g
               FROM transactions
               WHERE txn_type = 'OUT' AND txn_date BETWEEN :start AND :end"""
    params = {"start": start_date, "end": end_date}
    if store_id is not None:
        query += " AND store_id = :store"
        params["store"] = store_id
    query += " GROUP BY channel"

    with get_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()

    by_channel = {r["channel"] or "未分類": {
        "revenue": r["revenue"] or 0, "cogs": r["cogs"] or 0,
        "profit": r["profit"] or 0, "qty_g": r["qty_g"] or 0
    } for r in rows}
    total_revenue = sum(v["revenue"] for v in by_channel.values())
    total_cogs = sum(v["cogs"] for v in by_channel.values())
    total_profit = sum(v["profit"] for v in by_channel.values())
    margin = (total_profit / total_revenue * 100) if total_revenue else 0
    return {
        "start_date": start_date, "end_date": end_date, "store_id": store_id,
        "by_channel": by_channel, "total_revenue": total_revenue,
        "total_cogs": total_cogs, "total_profit": total_profit,
        "gross_margin_pct": margin
    }


def get_store_comparison(start_date: str, end_date: str) -> List[dict]:
    """多門店績效比較報表（第5點多門店支援的核心應用場景）"""
    with get_conn() as conn:
        store_ids = [r["store_id"] for r in conn.execute(
            text("SELECT store_id FROM stores WHERE is_active = 1")
        ).mappings().all()]
    return [
        {"store_id": sid, **get_profit_report(start_date, end_date, store_id=sid)}
        for sid in store_ids
    ]
