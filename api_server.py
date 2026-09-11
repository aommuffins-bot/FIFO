"""
api_server.py — A.O.M Cafe 進銷存 API v5
更新內容：
1. 進貨報表新增：當批次進貨價、進貨量(g)、出庫量(g)、供應商；批次欄位重新命名為「進貨日期」
2. 出貨報表：僅保留 OUT 類型交易、單價欄位標註 (g)、通路欄位支援自訂輸入
"""
from fastapi import FastAPI, Depends, HTTPException, Query, Form
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import jwt
import hashlib
import os

app = FastAPI(
    title="A.O.M Cafe 進銷存 API",
    version="5.0.0",
    description="FIFO 進銷存系統線上版（含 100 SKU 商品資料 + 報表欄位優化）",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aommuffins-bot.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.environ.get("AOM_JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"

USERS_DB = {
    "admin": {"user_id": 1, "username": "admin", "password_hash": hashlib.pbkdf2_hmac("sha256", "admin123".encode(), "salt123".encode(), 100000).hex(), "password_salt": "salt123", "role": "admin", "store_id": 1, "is_active": 1},
    "aom_founder": {"user_id": 2, "username": "aom_founder", "password_hash": hashlib.pbkdf2_hmac("sha256", "Dc20220111".encode(), "salt456".encode(), 100000).hex(), "password_salt": "salt456", "role": "admin", "store_id": 1, "is_active": 1},
}

# ==== PRODUCTS_DB 維持原 100 SKU（請依需要同步 seed_115sku 擴充內容） ====
PRODUCTS_DB = [
    {"sku_no": 1, "name": "耶加雪菲 Yirgacheffe G1", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "阿拉比卡/原生種", "flavor": "花香、茉莉、柑橘、明亮檸檬酸", "rating": "★★★★☆"},
    {"sku_no": 2, "name": "耶加雪菲 日曬 G1", "continent": "非洲", "country": "衣索比亞", "process": "日曬", "variety": "阿拉比卡/原生種", "flavor": "藍莓、熱帶水果、酒香、甜感飽滿", "rating": "★★★★☆"},
    {"sku_no": 3, "name": "西達摩 Sidama G2", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "阿拉比卡/原生種", "flavor": "巧克力、太妃糖、溫和果酸", "rating": "★★★★☆"},
    {"sku_no": 4, "name": "谷吉 Guji G1 日曬", "continent": "非洲", "country": "衣索比亞", "process": "日曬", "variety": "阿拉比卡/原生種", "flavor": "芒果、桃子、果凍感、甜感極佳", "rating": "★★★★☆"},
    {"sku_no": 5, "name": "哈拉 Harrar G4 日曬", "continent": "非洲", "country": "衣索比亞", "process": "日曬", "variety": "阿拉比卡/原生種", "flavor": "藍莓干、黑巧克力、狂野土壤味", "rating": "★★★★☆"},
    {"sku_no": 6, "name": "沃卡 Worka 合作社", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "阿拉比卡/原生種", "flavor": "玫瑰、茉莉、荔枝、優雅花果", "rating": "★★★★☆"},
    {"sku_no": 7, "name": "班奇馬吉 Bench Maji", "continent": "非洲", "country": "衣索比亞", "process": "蜜處理", "variety": "阿拉比卡/原生種", "flavor": "紅糖、苦橙皮、中厚實口感", "rating": "★★★★☆"},
    {"sku_no": 8, "name": "肯亞 AA 水洗", "continent": "非洲", "country": "肯亞", "process": "水洗", "variety": "SL28/SL34", "flavor": "黑醋栗、番茄、莓果酸感強烈", "rating": "★★★★☆"},
    {"sku_no": 9, "name": "肯亞 AB 水洗", "continent": "非洲", "country": "肯亞", "process": "水洗", "variety": "SL28/SL34", "flavor": "黑醋栗、柑橘、明亮酸", "rating": "★★★★☆"},
    {"sku_no": 10, "name": "基里尼亞加 Kirinyaga PB", "continent": "非洲", "country": "肯亞", "process": "水洗", "variety": "SL28/SL34", "flavor": "小圓豆，濃郁莓果、甜感集中", "rating": "★★★★☆"},
    {"sku_no": 11, "name": "盧安達 Muhondo 水洗", "continent": "非洲", "country": "盧安達", "process": "水洗", "variety": "波旁", "flavor": "紅蘋果、柑橘、甜感溫和", "rating": "★★★★☆"},
    {"sku_no": 12, "name": "蒲隆地 Kayanza 水洗", "continent": "非洲", "country": "蒲隆地", "process": "水洗", "variety": "波旁", "flavor": "覆盆莓、蜜桃、花香", "rating": "★★★★☆"},
    {"sku_no": 13, "name": "坦尚尼亞 AA Kilimanjaro", "continent": "非洲", "country": "坦尚尼亞", "process": "水洗", "variety": "波旁/肯特", "flavor": "黑糖、葡萄、中厚實", "rating": "★★★★☆"},
    {"sku_no": 14, "name": "剛果 Kivu 日曬", "continent": "非洲", "country": "剛果", "process": "日曬", "variety": "原生種", "flavor": "深果乾、可可豆、大地氣息", "rating": "★★★★☆"},
    {"sku_no": 15, "name": "葉門 Mokha 原生種", "continent": "非洲", "country": "葉門", "process": "日曬", "variety": "原生種混合", "flavor": "黑巧克力、野生莓果、複雜層次", "rating": "★★★★☆"},
    {"sku_no": 16, "name": "哥倫比亞 Huila Supremo", "continent": "中南美洲", "country": "哥倫比亞", "process": "水洗", "variety": "卡杜拉/蒂皮卡", "flavor": "焦糖、紅蘋果、溫和甜酸", "rating": "★★★★☆"},
    {"sku_no": 17, "name": "哥倫比亞 Nariño 水洗", "continent": "中南美洲", "country": "哥倫比亞", "process": "水洗", "variety": "卡杜拉", "flavor": "柑橘花香、明亮果酸、優雅", "rating": "★★★★☆"},
    {"sku_no": 18, "name": "哥倫比亞 厭氧日曬", "continent": "中南美洲", "country": "哥倫比亞", "process": "厭氧日曬", "variety": "卡杜拉", "flavor": "熱帶水果炸彈、濃烈發酵香", "rating": "★★★★☆"},
    {"sku_no": 19, "name": "哥倫比亞 El Paraiso 莊園", "continent": "中南美洲", "country": "哥倫比亞", "process": "厭氧蜜處理", "variety": "卡杜拉", "flavor": "菠蘿、荔枝、波本威士忌桶香", "rating": "★★★★☆"},
    {"sku_no": 20, "name": "哥倫比亞 Rosa 玫瑰日曬", "continent": "中南美洲", "country": "哥倫比亞", "process": "玫瑰日曬", "variety": "卡杜拉", "flavor": "玫瑰花茶、草莓、甜感優雅", "rating": "★★★★☆"},
    {"sku_no": 21, "name": "巴西 Santos NY2 日曬", "continent": "中南美洲", "country": "巴西", "process": "日曬", "variety": "波旁/卡杜拉", "flavor": "堅果、黑巧克力、低酸厚實", "rating": "★★★★☆"},
    {"sku_no": 22, "name": "巴西 Mogiana 日曬", "continent": "中南美洲", "country": "巴西", "process": "日曬", "variety": "波旁/卡杜拉", "flavor": "黃糖、堅果、柔順均衡", "rating": "★★★★☆"},
    {"sku_no": 23, "name": "巴西 黃波旁 日曬", "continent": "中南美洲", "country": "巴西", "process": "日曬", "variety": "黃波旁", "flavor": "桃子、杏仁、甜感突出", "rating": "★★★★☆"},
    {"sku_no": 24, "name": "巴西 Natural Pulped", "continent": "中南美洲", "country": "巴西", "process": "去果皮日曬", "variety": "波旁", "flavor": "焦糖、蜂蜜、輕果香", "rating": "★★★★☆"},
    {"sku_no": 25, "name": "巴西 CoE 競標批次", "continent": "中南美洲", "country": "巴西", "process": "日曬/水洗", "variety": "多品種", "flavor": "依批次，高分精品特色", "rating": "★★★★☆"},
    {"sku_no": 26, "name": "瓜地馬拉 Antigua SHB", "continent": "中南美洲", "country": "瓜地馬拉", "process": "水洗", "variety": "波旁/卡杜拉", "flavor": "黑糖、可可、輕煙燻", "rating": "★★★★☆"},
    {"sku_no": 27, "name": "瓜地馬拉 Huehuetenango", "continent": "中南美洲", "country": "瓜地馬拉", "process": "水洗", "variety": "波旁", "flavor": "花香、糖蜜、柑橘", "rating": "★★★★☆"},
    {"sku_no": 28, "name": "瓜地馬拉 蜜處理", "continent": "中南美洲", "country": "瓜地馬拉", "process": "蜜處理", "variety": "卡杜拉", "flavor": "甜感溫潤、焦糖、輕果香", "rating": "★★★★☆"},
    {"sku_no": 29, "name": "巴拿馬 藝伎 Geisha 水洗", "continent": "中南美洲", "country": "巴拿馬", "process": "水洗", "variety": "藝伎/Geisha", "flavor": "茉莉、佛手柑、蜂蜜、絲滑", "rating": "★★★★☆"},
    {"sku_no": 30, "name": "巴拿馬 藝伎 日曬", "continent": "中南美洲", "country": "巴拿馬", "process": "日曬", "variety": "藝伎/Geisha", "flavor": "熱帶水果炸彈、複雜層次", "rating": "★★★★☆"},
    {"sku_no": 31, "name": "巴拿馬 Elida 莊園 Geisha", "continent": "中南美洲", "country": "巴拿馬", "process": "水洗", "variety": "藝伎", "flavor": "BSCA全球高分，茶感、優雅", "rating": "★★★★☆"},
    {"sku_no": 32, "name": "Costa Rica Tarrazu SHB", "continent": "中南美洲", "country": "哥斯大黎加", "process": "水洗", "variety": "卡杜拉", "flavor": "柑橘、甜感、乾淨明亮", "rating": "★★★★☆"},
    {"sku_no": 33, "name": "Costa Rica 蜜處理 黃蜜", "continent": "中南美洲", "country": "哥斯大黎加", "process": "黃蜜", "variety": "卡杜拉", "flavor": "蜜桃、焦糖、低酸甜感", "rating": "★★★★☆"},
    {"sku_no": 34, "name": "Costa Rica 黑蜜處理", "continent": "中南美洲", "country": "哥斯大黎加", "process": "黑蜜", "variety": "卡杜拉", "flavor": "紅糖、莓果、複雜甜感", "rating": "★★★★☆"},
    {"sku_no": 35, "name": "宏都拉斯 Copan SHG", "continent": "中南美洲", "country": "宏都拉斯", "process": "水洗", "variety": "帕卡斯", "flavor": "焦糖、深色水果、溫和酸", "rating": "★★★★☆"},
    {"sku_no": 36, "name": "薩爾瓦多 Pacamara 日曬", "continent": "中南美洲", "country": "薩爾瓦多", "process": "日曬", "variety": "帕卡馬拉", "flavor": "甜蜜、熱帶水果、大顆粒", "rating": "★★★★☆"},
    {"sku_no": 37, "name": "尼加拉瓜 Jinotega 水洗", "continent": "中南美洲", "country": "尼加拉瓜", "process": "水洗", "variety": "卡杜拉/IHCAFE90", "flavor": "黑糖、焦糖、溫和莓果", "rating": "★★★★☆"},
    {"sku_no": 38, "name": "秘魯 Cajamarca 有機", "continent": "中南美洲", "country": "秘魯", "process": "水洗", "variety": "卡杜拉/典型種", "flavor": "堅果、可可、輕果酸", "rating": "★★★★☆"},
    {"sku_no": 39, "name": "玻利維亞 Caranavi 水洗", "continent": "中南美洲", "country": "玻利維亞", "process": "水洗", "variety": "蒂皮卡", "flavor": "柑橘、杏桃、清透感", "rating": "★★★★☆"},
    {"sku_no": 40, "name": "哥倫比亞 Castillo 厭氧水洗", "continent": "中南美洲", "country": "哥倫比亞", "process": "厭氧水洗", "variety": "Castillo", "flavor": "綠葡萄、火龍果、輕發酵香", "rating": "★★★★☆"},
    {"sku_no": 41, "name": "曼特寧 Mandheling G1", "continent": "亞洲", "country": "印尼", "process": "半水洗", "variety": "鐵比卡", "flavor": "黑土、松木、黑巧克力、低酸厚實", "rating": "★★★★☆"},
    {"sku_no": 42, "name": "托拉查 Toraja 半水洗", "continent": "亞洲", "country": "印尼", "process": "半水洗", "variety": "鐵比卡/卡杜拉", "flavor": "可可、辛香料、複雜土壤", "rating": "★★★★☆"},
    {"sku_no": 43, "name": "Gayo 蓋優 G1", "continent": "亞洲", "country": "印尼", "process": "半水洗/水洗", "variety": "鐵比卡", "flavor": "草本、肉桂、薄荷、獨特", "rating": "★★★★☆"},
    {"sku_no": 44, "name": "Flores Bajawa", "continent": "亞洲", "country": "印尼", "process": "水洗", "variety": "鐵比卡", "flavor": "薑汁、深色水果、厚重", "rating": "★★★★☆"},
    {"sku_no": 45, "name": "黃金曼特寧 Premium", "continent": "亞洲", "country": "印尼", "process": "半水洗", "variety": "鐵比卡", "flavor": "純淨、低酸、奶油堅果", "rating": "★★★★☆"},
    {"sku_no": 46, "name": "爪哇 Java 莊園", "continent": "亞洲", "country": "印尼", "process": "水洗", "variety": "鐵比卡", "flavor": "土壤、木質、均衡", "rating": "★★★★☆"},
    {"sku_no": 47, "name": "印度 Monsooned Malabar", "continent": "亞洲", "country": "印度", "process": "季風處理", "variety": "羅布斯塔/阿拉比卡", "flavor": "麥芽、木桶、低酸濃厚", "rating": "★★★★☆"},
    {"sku_no": 48, "name": "印度 Araku Valley 水洗", "continent": "亞洲", "country": "印度", "process": "水洗", "variety": "阿拉比卡", "flavor": "花香、可可、柑橘", "rating": "★★★★☆"},
    {"sku_no": 49, "name": "越南 大叻 Da Lat 阿拉比卡", "continent": "亞洲", "country": "越南", "process": "水洗", "variety": "卡杜拉", "flavor": "花香果酸、輕盈、中等甜感", "rating": "★★★★☆"},
    {"sku_no": 50, "name": "泰國 清邁 Doi Chang 水洗", "continent": "亞洲", "country": "泰國", "process": "水洗", "variety": "阿拉比卡", "flavor": "核桃、輕花香、甜感溫和", "rating": "★★★★☆"},
    {"sku_no": 51, "name": "泰國 Doi Tung 皇家計畫", "continent": "亞洲", "country": "泰國", "process": "水洗", "variety": "阿拉比卡", "flavor": "均衡甜感、花香、輕柑橘", "rating": "★★★★☆"},
    {"sku_no": 52, "name": "緬甸 Shan State 水洗", "continent": "亞洲", "country": "緬甸", "process
