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
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("dashboard")

QMT_BRIDGE = "http://172.31.144.1:8890"
POSITION_FILE = Path(__file__).parent.parent / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = Path(__file__).parent.parent / "00-研究" / "自选股" / "watchlist.json"
NOTIFICATION_FILE = Path(__file__).parent / "notifications.json"
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


@app.post("/api/position/add")
def add_position(
    code: str = Form(...),
    name: str = Form(...),
    shares: int = Form(...),
    cost: float = Form(...),
    buy_reason: str = Form(""),
    stop_loss: float = Form(0),
    level: str = Form("日线"),
    weekly_note: str = Form(""),
    daily_note: str = Form(""),
    min15_note: str = Form(""),
    target: str = Form(""),
    warning_line: float = Form(0),
    warning_meaning: str = Form(""),
    stop_loss_meaning: str = Form("跌破无条件止损"),
):
    """手动录入持仓"""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signal_date = datetime.now().strftime("%Y%m%d")

        # 构建买入依据
        buy_reason_data = {
            "级别": level,
            "周线": weekly_note or "-",
            "日线": daily_note or "-",
            "15分钟": min15_note or "-",
            "入场规则": buy_reason,
            "目标空间": target or "-",
            "止损价": stop_loss,
            "止损线含义": stop_loss_meaning,
            "预警线": warning_line or round(cost * 0.97, 2),
            "预警线含义": warning_meaning or "结构动摇信号",
            "盈亏比": f"1:{round((target and float(target) or cost) - cost) / (cost - stop_loss) if stop_loss else 1:.1f}" if stop_loss else "-",
        }

        # 读取现有持仓
        if POSITION_FILE.exists():
            with open(POSITION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {
                "更新时间": now,
                "信号日期": signal_date,
                "持仓汇总": {
                    "总资产": 0, "总市值": 0, "总盈亏": 0,
                    "总手续费": 0, "可用资金": 0, "持仓比例%": 0,
                    "持仓股数": 0, "初始资金": 1000000,
                },
                "持仓明细": [],
            }

        # 检查是否已存在该股票
        existing = [p for p in data.get("持仓明细", []) if p.get("股票代码") == code]
        if existing:
            # 更新已有持仓（追加股数、加权成本）
            old = existing[0]
            old_shares = old.get("持股数量", 0)
            old_cost = old.get("成本价", 0)
            total_shares = old_shares + shares
            total_cost = old_cost * old_shares + cost * shares
            new_cost = round(total_cost / total_shares, 3) if total_shares > 0 else cost
            old["持股数量"] = total_shares
            old["成本价"] = new_cost
            old["买入依据"] = buy_reason_data
            old["当前价"] = cost
            msg = f"已更新 {name}({code}) 持仓: {total_shares}股, 均价{new_cost}"
        else:
            # 新增持仓
            new_pos = {
                "股票代码": code,
                "名称": name,
                "持股数量": shares,
                "成本价": cost,
                "当前价": cost,
                "买入依据": buy_reason_data,
            }
            data.setdefault("持仓明细", []).append(new_pos)
            msg = f"已添加 {name}({code}) 持仓: {shares}股, 成本{cost}"

        # 更新汇总
        total_shares = sum(p.get("持股数量", 0) for p in data["持仓明细"])
        total_cost = sum(p.get("成本价", 0) * p.get("持股数量", 0) for p in data["持仓明细"])
        total_value = sum(p.get("当前价", p.get("成本价", 0)) * p.get("持股数量", 0) for p in data["持仓明细"])
        data["更新时间"] = now
        data["持仓汇总"].update({
            "总市值": round(total_value, 2),
            "总盈亏": round(total_value - total_cost, 2),
            "持仓股数": total_shares,
            "持仓比例%": round(total_value / max(data["持仓汇总"].get("初始资金", 1000000), 1) * 100, 2),
        })

        # 写入文件
        POSITION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(POSITION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 清理缓存
        with _cache_lock:
            _cache.pop("data", None)

        logger.info(f"持仓更新成功: {msg}")
        return {"ok": True, "message": msg}

    except Exception as e:
        logger.error(f"持仓更新失败: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "message": str(e)})


@app.post("/api/position/remove/{code}")
def remove_position(code: str):
    """移除持仓（供飞书卡片按钮调用）"""
    try:
        if not POSITION_FILE.exists():
            return {"success": False, "error": "持仓文件不存在"}

        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        detail = data.get("持仓明细", [])
        removed = [p for p in detail if p.get("股票代码") == code]
        data["持仓明细"] = [p for p in detail if p.get("股票代码") != code]

        # 更新汇总
        data["持仓汇总"]["持仓股数"] = sum(p.get("持股数量", 0) for p in data["持仓明细"])
        total_value = sum(
            p.get("持股数量", 0) * p.get("当前价", p.get("成本价", 0))
            for p in data["持仓明细"]
        )
        data["持仓汇总"]["总市值"] = total_value
        data["持仓汇总"]["持仓比例%"] = round(total_value / data["持仓汇总"].get("总资产", 1) * 100, 2) if data["持仓汇总"].get("总资产") else 0
        data["更新时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(POSITION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if removed:
            logger.info(f"持仓已移除: {code} {removed[0].get('名称', '')}")
            return {"success": True, "code": code, "name": removed[0].get("名称", "")}
        else:
            return {"success": False, "error": f"未找到持仓: {code}"}

    except Exception as e:
        logger.error(f"移除持仓失败: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/signals")
def get_signals(
    status: str = "pending",
    signal_type: str = "",
):
    """获取当前信号模板（供 Dashboard 展示）"""
    try:
        from state_store import StateStore
        store = StateStore()

        records = store.load_signal_templates(
            signal_type=signal_type if signal_type else None,
            status=status,
        )

        # 按类型分组
        grouped = {}
        for r in records:
            t = r["signal_type"]
            if t not in grouped:
                grouped[t] = []
            grouped[t].append(r)

        return {
            "total": len(records),
            "grouped": grouped,
            "update_time": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"获取信号失败: {e}")
        return {"total": 0, "grouped": {}, "error": str(e)}


@app.get("/api/notifications")
def get_notifications():
    """获取最近报警通知（供 Dashboard 轮询）"""
    if not NOTIFICATION_FILE.exists():
        return {
            "alerts": [],
            "updated_at": "",
            "indices": {},
            "alert_count": 0,
        }
    try:
        with open(NOTIFICATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.warning(f"读取通知文件失败: {e}")
        return {
            "alerts": [],
            "updated_at": "",
            "indices": {},
            "alert_count": 0,
            "error": str(e),
        }


# ============================================================
# 信号生命周期管理 API
# ============================================================

@app.api_route("/api/signal/acknowledge/{signal_id}", methods=["GET", "POST"])
def acknowledge_signal(request: Request, signal_id: int, notes: str = ""):
    """确认已收到信号通知。GET(飞书按钮)=HTML自动关闭, POST(API)=JSON"""
    try:
        from state_store import StateStore
        store = StateStore()
        ok = store.acknowledge_signal(signal_id, notes=notes)

        # POST -> JSON
        if request.method == "POST":
            if ok:
                return {"success": True, "message": f"信号 {signal_id} 已确认"}
            else:
                return JSONResponse(status_code=404,
                    content={"success": False, "error": f"信号 {signal_id} 未找到或状态不允许确认"})

        # GET(飞书按钮) -> 自动关闭的HTML页面
        if ok:
            logger.info(f"信号确认: ID={signal_id}")
            html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>确认成功</title>'
            html += '<style>*{margin:0;padding:0;}body{font-family:sans-serif;text-align:center;padding:60px 20px;background:#f5f5f5;}'
            html += '.card{background:#fff;border-radius:12px;padding:40px;max-width:400px;margin:0 auto;box-shadow:0 2px 12px rgba(0,0,0,0.1);}'
            html += '.icon{font-size:64px;}h2{color:#333;margin:16px 0 8px;}p{color:#666;}</style></head><body>'
            html += f'<div class="card"><div class="icon">\U00002705</div><h2>\u4fe1\u53f7\u5df2\u786e\u8ba4</h2>'
            html += f'<p>\u4fe1\u53f7 #{signal_id} \u5df2\u6807\u8bb0\u4e3a\u300c\u5df2\u6536\u5230\u300d\uff0c\u4e0d\u518d\u91cd\u590d\u901a\u77e5\u3002</p>'
            html += '<p style="font-size:12px;color:#999;">\u6b64\u9875\u9762\u5c06\u81ea\u52a8\u5173\u95ed</p></div>'
            html += '<script>setTimeout(function(){window.close();},1500);</script></body></html>'
            return HTMLResponse(content=html)
        else:
            html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>\u786e\u8ba4\u5931\u8d25</title>'
            html += '<style>body{font-family:sans-serif;text-align:center;padding:60px;}</style></head><body>'
            html += f'<h2>\u26a0\ufe0f \u786e\u8ba4\u5931\u8d25</h2><p>\u4fe1\u53f7 #{signal_id} \u672a\u627e\u5230\u6216\u5df2\u88ab\u786e\u8ba4\u8fc7</p></body></html>'
            return HTMLResponse(content=html, status_code=404)
    except Exception as e:
        logger.error(f"\u786e\u8ba4\u4fe1\u53f7\u5931\u8d25: {e}")
        return HTMLResponse(content=f"<h2>\u786e\u8ba4\u5931\u8d25</h2><p>{e}</p>", status_code=500)



@app.post("/api/signal/complete/{signal_id}")
def complete_signal(signal_id: int, operation_notes: str = ""):
    """
    标记信号对应的操作已完成（如止损卖出、止盈减仓）。

    状态流转: acknowledged → completed
    完成后信号永久保留在DB中供复盘使用。
    """
    try:
        from state_store import StateStore
        store = StateStore()
        ok = store.complete_signal(signal_id, operation_notes=operation_notes)
        if ok:
            logger.info(f"信号完成: ID={signal_id} notes={operation_notes}")
            return {"success": True, "message": f"信号 {signal_id} 已完成"}
        else:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"信号 {signal_id} 未找到或状态不允许完成"}
            )
    except Exception as e:
        logger.error(f"完成信号失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/signal/history")
def get_signal_history(
    signal_type: str = "",
    status: str = "",
    stock_code: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """
    获取信号历史记录（含所有状态），供复盘分析。

    支持按类型、状态、股票代码筛选，按时间倒序排列。
    """
    try:
        from state_store import StateStore
        store = StateStore()
        result = store.get_signal_history(
            signal_type=signal_type if signal_type else None,
            status=status if status else None,
            stock_code=stock_code if stock_code else None,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        logger.error(f"获取历史信号失败: {e}")
        return {"total": 0, "signals": [], "error": str(e)}


@app.get("/api/signal/stats")
def get_signal_stats():
    """获取信号统计，用于复盘分析系统的信号识别灵敏度和准确率"""
    try:
        from state_store import StateStore
        store = StateStore()

        # 各状态数量
        all_statuses = ["pending", "activated", "acknowledged", "completed", "invalidated", "expired"]
        stats = {}
        for s in all_statuses:
            records = store.load_signal_templates(status=s)
            stats[s] = len(records)

        # 按信号类型统计
        type_stats = {}
        for t in ["bottom_fractal", "top_fractal", "divergence_zone", "position_risk"]:
            records = store.load_signal_templates(signal_type=t)
            type_stats[t] = len(records)

        return {
            "by_status": stats,
            "by_type": type_stats,
            "total": sum(stats.values()),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"获取信号统计失败: {e}")
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    if DASHBOARD_HTML.exists():
        html = DASHBOARD_HTML.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Dashboard 页面未找到</h1>", status_code=404)


if __name__ == "__main__":
    logger.info("Dashboard 服务启动 → http://0.0.0.0:8891")
    uvicorn.run(app, host="0.0.0.0", port=8891)
