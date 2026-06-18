# -*- coding: utf-8 -*-
"""
盯盘 Dashboard 服务（Linux端）
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from datetime import datetime as dt

import uvicorn
from sector_data import get_sector
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("dashboard")

QMT_BRIDGE = "http://172.31.144.1:8890"
POSITION_FILE = Path(__file__).parent.parent / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = Path(__file__).parent.parent / "00-研究" / "自选股" / "watchlist.json"
TEMPLATES_DIR = Path(__file__).parent / "templates"
DASHBOARD_HTML = TEMPLATES_DIR / "dashboard.html"

app = FastAPI(title="盯盘 Dashboard")

# 缓存
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 8  # 缓存8秒


def load_positions() -> List[Dict]:
    if not POSITION_FILE.exists():
        return []
    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("持仓明细", [])
    except Exception:
        return []


def load_watchlist() -> List[Dict]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def fetch_quotes(codes: List[str]) -> Dict:
    """获取行情，大批量时分批并行请求"""
    if not codes:
        return {}
    BATCH = 60
    if len(codes) <= BATCH:
        try:
            resp = requests.get(f"{QMT_BRIDGE}/api/quotes/batch", params={"codes": ",".join(codes)}, timeout=20)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logger.warning(f"获取行情失败: {e}")
            return {}
    import concurrent.futures
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        fs = {}
        for i in range(0, len(codes), BATCH):
            b = codes[i:i+BATCH]
            f = ex.submit(requests.get, f"{QMT_BRIDGE}/api/quotes/batch",
                         params={"codes": ",".join(b)}, timeout=20)
            fs[f] = b
        for f in concurrent.futures.as_completed(fs):
            try:
                r = f.result()
                if r.status_code == 200:
                    result.update(r.json())
            except:
                pass
    return result


def rank_stocks(stocks: List[Dict], quotes: Dict) -> List[Dict]:
    scored = []
    for s in stocks:
        code = s.get("code", "")
        if not code or code.startswith("399") or code.startswith("880"):
            continue
        qmt_code = f"{code}.SH" if (code.startswith("6") or code.startswith("9")) else f"{code}.SZ"
        quote = quotes.get(qmt_code, {})
        change_pct = abs(quote.get("change_pct", 0))
        volume = quote.get("volume", 0)
        score = change_pct * 0.4 + min(volume / 1000000, 10) * 0.3
        sec = get_sector(code)
        scored.append({
            "code": code,
            "name": quote.get("name", s.get("name", code)),
            "market": s.get("market", ""),
            "price": quote.get("price", 0),
            "change_pct": quote.get("change_pct", 0),
            "volume": volume,
            "amount": quote.get("amount", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "score": round(score, 2),
            "industry": sec.get("行业", ""),
            "concept": sec.get("概念", ""),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


@app.get("/api/dashboard")
def api_dashboard():
    with _cache_lock:
        now = datetime.now()
        if "data" in _cache and (now - _cache["time"]).seconds < CACHE_TTL:
            return _cache["data"]

    positions = load_positions()
    watchlist = load_watchlist()

    position_codes = []
    for p in positions:
        code = p.get("股票代码", "")
        qc = f"{code}.SH" if (code.startswith("6") or code.startswith("9")) else f"{code}.SZ"
        position_codes.append(qc)

    raw_codes = []
    for w in watchlist:
        code = w.get("code", "") if isinstance(w, dict) else w
        if code and not code.startswith("399") and not code.startswith("880"):
            raw_codes.append(code)

    watchlist_qmt = []
    for c in raw_codes:
        qc = f"{c}.SH" if (c.startswith("6") or c.startswith("9")) else f"{c}.SZ"
        watchlist_qmt.append(qc)

    index_codes = ["000001.SH", "399001.SZ", "000300.SH", "399006.SZ"]
    all_codes = list(set(position_codes + watchlist_qmt + index_codes))
    quotes = fetch_quotes(all_codes)

    # 指数
    indices = {}
    idx_map = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "000300.SH": "沪深300", "399006.SZ": "创业板指"}
    for qc, name in idx_map.items():
        if qc in quotes:
            d = quotes[qc]
            indices[qc] = {"name": name, "price": d.get("price"), "change_pct": d.get("change_pct")}

    # 持仓
    position_data = []
    for p in positions:
        code = p.get("股票代码", "")
        qc = f"{code}.SH" if (code.startswith("6") or code.startswith("9")) else f"{code}.SZ"
        quote = quotes.get(qc, {})
        cost = p.get("成本价", 0)
        price = quote.get("price", 0) or p.get("当前价", cost)
        pnl_pct = (price - cost) / cost * 100 if cost else 0
        buy_reason = p.get("买入依据", {})
        position_data.append({
            "code": code,
            "name": quote.get("name", p.get("名称", code)),
            "shares": p.get("持股数量", 0),
            "cost": cost,
            "price": price,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amt": round((price - cost) * p.get("持股数量", 0), 2),
            "buy_reason": buy_reason if isinstance(buy_reason, dict) else {"信号": str(buy_reason)},
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
        })

    # Top 10
    ranked = rank_stocks(watchlist, quotes)
    top10 = ranked[:10]

    # 全部自选股
    all_watchlist = ranked

    result = {
        "indices": indices,
        "positions": position_data,
        "top10": top10,
        "watchlist": all_watchlist,
        "total_watchlist": len(watchlist),
        "update_time": datetime.now().strftime("%H:%M:%S"),
    }

    with _cache_lock:
        _cache["data"] = result
        _cache["time"] = datetime.now()

    return result


@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    if DASHBOARD_HTML.exists():
        html = DASHBOARD_HTML.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Dashboard 页面未找到</h1>", status_code=404)


if __name__ == "__main__":
    logger.info("Dashboard 服务启动 → http://0.0.0.0:8891")
    uvicorn.run(app, host="0.0.0.0", port=8891)
