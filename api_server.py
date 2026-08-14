"""
api_server.py — A.O.M Cafe 進銷存 API v3（含 100 SKU 完整種子資料）
"""
from fastapi import FastAPI, Depends, HTTPException, Query
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
    version="3.0.0",
    description="FIFO 進銷存系統線上版（含 100 SKU 完整商品資料）",
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
ACCESS_TOKEN_EXPIRE_MINUTES = 60

USERS_DB = {
    "admin": {"user_id": 1, "username": "admin", "password_hash": hashlib.pbkdf2_hmac("sha256", "admin123".encode(), "salt123".encode(), 100000).hex(), "password_salt": "salt123", "role": "admin", "store_id": 1, "is_active": 1},
    "aom_founder": {"user_id": 2, "username": "aom_founder", "password_hash": hashlib.pbkdf2_hmac("sha256", "Dc20220111".encode(), "salt456".encode(), 100000).hex(), "password_salt": "salt456", "role": "admin", "store_id": 1, "is_active": 1},
}

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
    {"sku_no": 52, "name": "緬甸 Shan State 水洗", "continent": "亞洲", "country": "緬甸", "process": "水洗", "variety": "阿拉比卡", "flavor": "草本、柑橘皮、輕酸", "rating": "★★★★☆"},
    {"sku_no": 53, "name": "雲南 保山 日曬", "continent": "亞洲", "country": "中國雲南", "process": "日曬", "variety": "卡杜拉/卡蒂莫", "flavor": "熱帶水果、草本、輕烘首選", "rating": "★★★★☆"},
    {"sku_no": 54, "name": "菲律賓 Sagada 水洗", "continent": "亞洲", "country": "菲律賓", "process": "水洗", "variety": "本地品種", "flavor": "溫和花香、輕甜感、低酸", "rating": "★★★★☆"},
    {"sku_no": 55, "name": "東帝汶 Timor 水洗", "continent": "亞洲", "country": "帝汶", "process": "水洗", "variety": "海布里多/帝汶混種", "flavor": "土壤、草本、偶發莓果", "rating": "★★★★☆"},
    {"sku_no": 56, "name": "阿里山 鐵比卡 日曬", "continent": "台灣", "country": "台灣-嘉義", "process": "日曬", "variety": "鐵比卡", "flavor": "花香、桃子、甜感、明亮", "rating": "★★★★☆"},
    {"sku_no": 57, "name": "阿里山 藝伎 Geisha 日曬", "continent": "台灣", "country": "台灣-嘉義", "process": "日曬", "variety": "藝伎", "flavor": "極致花香、茉莉、國際驚艷", "rating": "★★★★☆"},
    {"sku_no": 58, "name": "南投 埔里 日月潭 水洗", "continent": "台灣", "country": "台灣-南投", "process": "水洗", "variety": "鐵比卡", "flavor": "柑橘、焦糖、溫和甜感", "rating": "★★★★☆"},
    {"sku_no": 59, "name": "古坑咖啡 水洗", "continent": "台灣", "country": "台灣-雲林", "process": "水洗", "variety": "鐵比卡", "flavor": "黑糖、烏梅、台式溫潤", "rating": "★★★★☆"},
    {"sku_no": 60, "name": "屏東 三地門 日曬", "continent": "台灣", "country": "台灣-屏東", "process": "日曬", "variety": "阿拉比卡", "flavor": "芒果、熱帶果香、南台灣風土", "rating": "★★★★☆"},
    {"sku_no": 61, "name": "花蓮 玉里 水洗", "continent": "台灣", "country": "台灣-花蓮", "process": "水洗", "variety": "鐵比卡", "flavor": "清爽花香、輕甜、東台灣純淨", "rating": "★★★★☆"},
    {"sku_no": 62, "name": "台東 卑南 日曬", "continent": "台灣", "country": "台灣-台東", "process": "日曬", "variety": "鐵比卡", "flavor": "果乾、溫和甜感、輕發酵", "rating": "★★★★☆"},
    {"sku_no": 63, "name": "南投 鹿谷 蜜處理", "continent": "台灣", "country": "台灣-南投", "process": "蜜處理", "variety": "鐵比卡/卡杜拉", "flavor": "茶感、輕蜂蜜、清甜", "rating": "★★★★☆"},
    {"sku_no": 64, "name": "番路 SCAA 競賽豆", "continent": "台灣", "country": "台灣-嘉義", "process": "水洗/日曬", "variety": "多品種", "flavor": "依批次，國際賽事品質", "rating": "★★★★☆"},
    {"sku_no": 65, "name": "梅山 有機認證 水洗", "continent": "台灣", "country": "台灣-嘉義", "process": "水洗", "variety": "鐵比卡", "flavor": "花香清爽、輕酸、有機認證", "rating": "★★★★☆"},
    {"sku_no": 66, "name": "衣索比亞 厭氧發酵 Anaerobic", "continent": "非洲", "country": "衣索比亞", "process": "厭氧日曬", "variety": "原生種", "flavor": "酒香、熱帶果汁、強烈個性", "rating": "★★★★☆"},
    {"sku_no": 67, "name": "哥倫比亞 Caturra 天然發酵", "continent": "中南美洲", "country": "哥倫比亞", "process": "天然發酵", "variety": "卡杜拉", "flavor": "覆盆莓、發酵果汁感", "rating": "★★★★☆"},
    {"sku_no": 68, "name": "巴拿馬 SL28 微批次", "continent": "中南美洲", "country": "巴拿馬", "process": "水洗", "variety": "SL28", "flavor": "莓果、柑橘、濃郁", "rating": "★★★★☆"},
    {"sku_no": 69, "name": "肯亞 Washed Batian", "continent": "非洲", "country": "肯亞", "process": "水洗", "variety": "Batian", "flavor": "黑醋栗加強版、層次豐富", "rating": "★★★★☆"},
    {"sku_no": 70, "name": "CR Honey Thermal Shock", "continent": "中南美洲", "country": "哥斯大黎加", "process": "熱衝擊蜜", "variety": "卡杜拉", "flavor": "獨特冷熱衝擊，甜感翻倍", "rating": "★★★★☆"},
    {"sku_no": 71, "name": "印尼 黃金日曬 Wet Hulled", "continent": "亞洲", "country": "印尼", "process": "濕剝法日曬", "variety": "鐵比卡", "flavor": "陳年感、木桶、厚實", "rating": "★★★★☆"},
    {"sku_no": 72, "name": "哥倫比亞 Carbonic Maceration", "continent": "中南美洲", "country": "哥倫比亞", "process": "二氧化碳浸漬", "variety": "卡杜拉", "flavor": "葡萄酒香、清透、精密處理", "rating": "★★★★☆"},
    {"sku_no": 73, "name": "巴西 Anaerobic Natural", "continent": "中南美洲", "country": "巴西", "process": "厭氧日曬", "variety": "黃波旁", "flavor": "熱帶水果、深度甜感、酒香", "rating": "★★★★☆"},
    {"sku_no": 74, "name": "盧安達 CM Washing Station", "continent": "非洲", "country": "盧安達", "process": "二氧化碳浸漬水洗", "variety": "波旁", "flavor": "清透莓果、精準風味", "rating": "★★★★☆"},
    {"sku_no": 75, "name": "瓜地馬拉 Catuai 日曬", "continent": "中南美洲", "country": "瓜地馬拉", "process": "日曬", "variety": "卡杜艾", "flavor": "深色水果、黑糖、厚實", "rating": "★★★★☆"},
    {"sku_no": 76, "name": "印度 Bababudan Washed", "continent": "亞洲", "country": "印度", "process": "水洗", "variety": "肯特", "flavor": "巧克力、輕香料、溫和", "rating": "★★★★☆"},
    {"sku_no": 77, "name": "衣索比亞 Shakiso G1", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "原生種", "flavor": "茉莉、覆盆莓、最高分耶加", "rating": "★★★★☆"},
    {"sku_no": 78, "name": "哥倫比亞 Pink Bourbon 粉波旁", "continent": "中南美洲", "country": "哥倫比亞", "process": "水洗", "variety": "粉波旁", "flavor": "玫瑰荔枝、草莓、極甜感", "rating": "★★★★☆"},
    {"sku_no": 79, "name": "衣索比亞 Bombe G1 日曬", "continent": "非洲", "country": "衣索比亞", "process": "日曬", "variety": "原生種", "flavor": "番茄汁、熱帶水果、深邃", "rating": "★★★★☆"},
    {"sku_no": 80, "name": "哥倫比亞 Yeast Ferment 酵母發酵", "continent": "中南美洲", "country": "哥倫比亞", "process": "酵母加強發酵", "variety": "卡杜拉", "flavor": "桂皮、可可、複雜美學", "rating": "★★★★☆"},
    {"sku_no": 81, "name": "衣索比亞 Kochere 水洗", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "原生種", "flavor": "檀香、佛手柑、絲滑質地", "rating": "★★★★☆"},
    {"sku_no": 82, "name": "肯亞 Nyeri 水洗", "continent": "非洲", "country": "肯亞", "process": "水洗", "variety": "SL28/SL34", "flavor": "黑莓、蜂蜜、飽滿酸甜", "rating": "★★★★☆"},
    {"sku_no": 83, "name": "衣索比亞 Limu 水洗", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "原生種", "flavor": "檸檬草、蜂蜜、柔和均衡", "rating": "★★★★☆"},
    {"sku_no": 84, "name": "馬拉威 Mzuzu 水洗", "continent": "非洲", "country": "馬拉威", "process": "水洗", "variety": "波旁/卡杜拉", "flavor": "柑橘、堅果、輕發酵香", "rating": "★★★★☆"},
    {"sku_no": 85, "name": "尚比亞 Terranova 莊園", "continent": "非洲", "country": "尚比亞", "process": "水洗", "variety": "波旁", "flavor": "紅茶、柑橘、細膻優雅", "rating": "★★★★☆"},
    {"sku_no": 86, "name": "墨西哥 Chiapas 水洗", "continent": "中南美洲", "country": "墨西哥", "process": "水洗", "variety": "波旁/典型種", "flavor": "堅果、可可、溫和甜感", "rating": "★★★★☆"},
    {"sku_no": 87, "name": "厄瓜多 Loja 水洗", "continent": "中南美洲", "country": "厄瓜多", "process": "水洗", "variety": "卡杜拉", "flavor": "花香、蘋果、清爽明亮", "rating": "★★★★☆"},
    {"sku_no": 88, "name": "巴西 Geisha 日曬", "continent": "中南美洲", "country": "巴西", "process": "日曬", "variety": "藝伎", "flavor": "花香、蜂蜜、意外的細膻感", "rating": "★★★★☆"},
    {"sku_no": 89, "name": "哥倫比亞 Tabi 水洗", "continent": "中南美洲", "country": "哥倫比亞", "process": "水洗", "variety": "Tabi", "flavor": "柑橘、花香、獨特品種風味", "rating": "★★★★☆"},
    {"sku_no": 90, "name": "瓜地馬拉 Pacamara 蜜處理", "continent": "中南美洲", "country": "瓜地馬拉", "process": "蜜處理", "variety": "帕卡馬拉", "flavor": "熱帶水果、大顆粒、飽滿甜感", "rating": "★★★★☆"},
    {"sku_no": 91, "name": "蘇拉維西 Sulawesi Kalosi", "continent": "亞洲", "country": "印尼", "process": "半水洗", "variety": "S795", "flavor": "草本、辛香、厚實低酸", "rating": "★★★★☆"},
    {"sku_no": 92, "name": "雲南 潞江壩 蜜處理", "continent": "亞洲", "country": "中國", "process": "蜜處理", "variety": "卡蒂莫", "flavor": "焦糖、熱帶果香、新興產區話題", "rating": "★★★★☆"},
    {"sku_no": 93, "name": "巴紐 Sigri 水洗", "continent": "亞洲", "country": "巴布亞紐幾內亞", "process": "水洗", "variety": "阿魯沙/藍山", "flavor": "花香、柑橘、清爽明亮", "rating": "★★★★☆"},
    {"sku_no": 94, "name": "太和 蜜處理", "continent": "台灣", "country": "台灣-嘉義", "process": "蜜處理", "variety": "鐵比卡", "flavor": "蜂蜜、輕花香、圓潤口感", "rating": "★★★★☆"},
    {"sku_no": 95, "name": "國姓 日曬", "continent": "台灣", "country": "台灣-南投", "process": "日曬", "variety": "鐵比卡", "flavor": "果乾、甜感厚實、南投風土", "rating": "★★★★☆"},
    {"sku_no": 96, "name": "古坑 蜜處理 限定批", "continent": "台灣", "country": "台灣-雲林", "process": "蜜處理", "variety": "鐵比卡", "flavor": "焦糖、烏梅、台式甜感升級版", "rating": "★★★★☆"},
    {"sku_no": 97, "name": "巴拿馬 Esmeralda 莊園 水洗", "continent": "中南美洲", "country": "巴拿馬", "process": "水洗", "variety": "藝伎/卡杜拉", "flavor": "茉莉、蜂蜜、經典莊園代表", "rating": "★★★★☆"},
    {"sku_no": 98, "name": "衣索比亞 99合作社 水洗", "continent": "非洲", "country": "衣索比亞", "process": "水洗", "variety": "原生種", "flavor": "花香、荔枝、極致純淨感", "rating": "★★★★☆"},
    {"sku_no": 99, "name": "哥倫比亞 Sudan Rume 蘇丹魯迷", "continent": "中南美洲", "country": "哥倫比亞", "process": "水洗", "variety": "蘇丹魯迷", "flavor": "草本、柑橘、罕見基因品種", "rating": "★★★★☆"},
    {"sku_no": 100, "name": "印度 有機認證 水洗", "continent": "亞洲", "country": "印度", "process": "水洗", "variety": "阿拉比卡", "flavor": "溫和花香、堅果、有機認證", "rating": "★★★★☆"},
]

INVENTORY_DB = {p["sku_no"]: {"sku_no": p["sku_no"], "name": p["name"], "batches": [], "total_qty_g": 0.0} for p in PRODUCTS_DB}
TRANSACTIONS_DB = []

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    store_id: int

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

class SuccessResponse(BaseModel):
    status: str
    message: str
    new_total_qty_g: Optional[float] = None
    batches_used: Optional[List[dict]] = None

class ProductItem(BaseModel):
    sku_no: int
    name: str
    continent: str
    country: str
    process: str
    variety: str
    flavor: str
    rating: str

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()

def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=60)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
        user = USERS_DB.get(username)
        if not user or not user["is_active"]:
            raise HTTPException(status_code=401, detail="User not found", headers={"WWW-Authenticate": "Bearer"})
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})

@app.get("/")
async def root():
    return {"message": "A.O.M Cafe 進銷存 API v3.0.0", "status": "online", "total_sku": len(PRODUCTS_DB)}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/auth/login", response_model=Token, summary="使用者登入")
async def login_for_access_token(username: str = Query(...), password: str = Query(...)):
    user = USERS_DB.get(username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    pw_hash = hash_password(password, user["password_salt"])
    if pw_hash != user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    access_token = create_access_token({"sub": user["username"], "role": user["role"], "store_id": user["store_id"]})
    return {"access_token": access_token, "token_type": "bearer", "role": user["role"], "store_id": user["store_id"]}

@app.get("/products", response_model=List[ProductItem], summary="取得所有商品資料（100 SKU）")
async def get_products():
    return PRODUCTS_DB

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
        if req.sku_no not in INVENTORY_DB:
            raise HTTPException(status_code=400, detail="Invalid SKU")
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
    except HTTPException:
        raise
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
    csv_content = "SKU,品名,庫存量(g),批次數\n"
    for sku_no, item in INVENTORY_DB.items():
        csv_content += f"{sku_no},{item['name']},{item['total_qty_g']},{len(item['batches'])}\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})

@app.get("/reports/transactions")
async def export_transactions_report(store_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    if current_user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    csv_content = "日期,類型,SKU,數量(g),單價,總額,通路\n"
    for t in TRANSACTIONS_DB:
        csv_content += f"{t['txn_date']},{t['txn_type']},{t['sku_no']},{t['qty_g']},{t['unit_price_ntd_per_g']},{t['total_amount_ntd']},{t['channel']}\n"
    return PlainTextResponse(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions_report.csv"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
