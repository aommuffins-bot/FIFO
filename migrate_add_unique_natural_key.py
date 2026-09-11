"""
migrate_add_unique_natural_key.py -- 資料庫遷移：新增自然鍵唯一性限制
------------------------------------------------------------------------
為 products 資料表的 (continent, country, name) 組合建立唯一索引，
防止未來因命名疏失而產生重複商品，確保 seed_135sku.py 的自然鍵比對邏輯
（依 continent+country+name 尋找既有商品）永遠只會找到「唯一」一筆結果。

技術說明：
- SQLite 與 PostgreSQL 皆「不」直接支援 ALTER TABLE ... ADD CONSTRAINT UNIQUE
  這個語法（SQLite 的 ALTER TABLE 功能非常有限，不支援新增限制式）。
- 改用可攜（portable）的 CREATE UNIQUE INDEX 語法，兩種資料庫皆完整支援，
  效果與 UNIQUE CONSTRAINT 完全相同（唯一索引本身就會強制唯一性）。
- 執行前會先檢查是否已有重複的自然鍵組合；若有重複，遷移會中止並列出
  重複清單，需要先手動處理重複資料才能繼續建立唯一索引
  （否則 CREATE UNIQUE INDEX 本身會因違反唯一性而失敗）。
- 使用 IF NOT EXISTS，可重複執行而不會出錯（idempotent），
  適合掛在 api_server.py 的啟動流程中，每次部署自動執行一次。
"""
from sqlalchemy import text
from db_engine import get_conn, init_db

CHECK_DUPLICATES_SQL = text("""
SELECT continent, country, name, COUNT(*) as cnt
FROM products
GROUP BY continent, country, name
HAVING COUNT(*) > 1
""")

CREATE_UNIQUE_INDEX_SQL = text("""
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_natural_key
ON products (continent, country, name)
""")


def migrate():
    """
    執行遷移：
    1. 先檢查 products 表是否已有重複的 (continent, country, name) 組合
    2. 若有重複 -> 印出清單並中止遷移（回傳 False），不會建立索引
    3. 若無重複 -> 建立唯一索引（回傳 True）
    """
    init_db()
    with get_conn() as conn:
        duplicates = conn.execute(CHECK_DUPLICATES_SQL).mappings().all()
        if duplicates:
            print("遷移中止：發現以下重複的自然鍵組合，請先手動處理後再重新執行：")
            for d in duplicates:
                print("  - " + d["continent"] + " / " + d["country"] + " / " + d["name"] +
                      " (共 " + str(d["cnt"]) + " 筆)")
            return False
        conn.execute(CREATE_UNIQUE_INDEX_SQL)
        print("遷移完成：已建立 uq_products_natural_key 唯一索引")
        return True


if __name__ == "__main__":
    migrate()