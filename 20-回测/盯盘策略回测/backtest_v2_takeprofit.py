#!/usr/bin/env python3
"""
盯盘策略回测 — 最终定版

核心规则：
1. 买入：二买优先级>类二买>三买，均来自缠论严格定义
2. 卖出：15分钟顶背驰 + 缠论一卖/二卖信号
3. 止盈：持仓浮盈达到30%时减半仓，释放现金继续买入
4. 止损：底分型振幅≤5%用third_low，>5%用中位
5. 成交量过滤：突破当日成交量 > 5日均量的1.5倍
4. 卖出：到达15分钟背驰/一卖/二卖/止损时，清掉剩余仓位
5. 不设固定持仓上限（但受限于现金和交易机会数量）
"""

import os, sys, json, math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict

import numpy as np
import pandas as pd

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))

try:
    from chanlun_core import ChanlunCore, FractalType, Direction
except ImportError as e:
    print(f"❌ 无法导入缠论核心模块: {e}")
    sys.exit(1)

# 共享策略配置
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
from strategy_config import (
    BUY_SIGNAL_PRIORITY, VOLUME_RATIO, TAKEPROFIT_PCT,
    FRACTAL_AMPLITUDE_THRESHOLD, SIGNAL_TYPE_CN,
)

# ── 路径常量 ──
WATCHLIST_FILE = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
KLINE_5M_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_5m_adj"
KLINE_DAY_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_day"
OUTPUT_DIR = Path(__file__).parent / f"回测结果_final_{datetime.now().strftime('%Y%m%d_%H%M')}"

# ── 交易参数 ──
INITIAL_CAPITAL = 10_000.0
COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE = 0.001
MAX_FRACTAL_AGE = 60
MIN_BUY_SCORE = 90
TAKEPROFIT_PCT = 0.30  # 浮盈30%减半仓

BACKTEST_END = datetime(2026, 7, 2)
BACKTEST_START = datetime(2024, 7, 2)
MAX_POSITIONS = 999  # 不设硬上限,现金就是上限


# ═══════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════

def load_all_stocks() -> List[Dict]:
    """从 kline_day 加载全市场股票列表（剔除科创板）"""
    if not KLINE_DAY_DIR.exists():
        print(f"❌ 日线目录不存在: {KLINE_DAY_DIR}")
        return []

    stocks = []
    for fname in sorted(os.listdir(KLINE_DAY_DIR)):
        if not fname.endswith(".csv"):
            continue
        full_code = fname.replace(".csv", "")
        if full_code.startswith("sh688"):
            continue  # 跳过科创板
        # full_code 格式: "sh600519" 或 "sz002202"
        if full_code.startswith("sh"):
            code = full_code[2:]
        elif full_code.startswith("sz"):
            code = full_code[2:]
        else:
            continue
        stocks.append({"code": code, "full_code": full_code, "name": code})
    print(f"📋 全市场股票: {len(stocks)} 只（已剔除科创板）")
    return stocks


def load_kline_day(full_code: str) -> Optional[pd.DataFrame]:
    """读取日线K线数据"""
    csv_path = KLINE_DAY_DIR / f"{full_code}.csv"
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["time"].astype(str), format="%Y%m%d")
        df = df.dropna(subset=["date", "close"])
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        return None


def fetch_kline_5m(full_code: str) -> Optional[pd.DataFrame]:
    """按需获取5分钟K线数据 — 优先本地缓存，其次QMT桥接，最后akshare"""
    # 1. 检查本地缓存
    csv_path = KLINE_5M_DIR / f"{full_code}.csv"
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S")
            df["date"] = df["datetime"].dt.date
            df = df.dropna(subset=["datetime", "close"])
            df = df.sort_values("datetime").reset_index(drop=True)
            for col in ["open", "high", "low", "close"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            pass

    # 2. 从 QMT 桥接获取（最近60个交易日）
    try:
        import urllib.request as _ureq, json as _json
        if full_code.startswith("sh"):
            qmt_code = f"{full_code[2:]}.SH"
        else:
            qmt_code = f"{full_code[2:]}.SZ"
        url = f"http://172.31.144.1:8890/api/kline?code={qmt_code}&period=5m&count=2880"
        resp = _ureq.urlopen(url, timeout=10)
        data = _json.loads(resp.read())
        bars = data.get("data", [])
        if len(bars) > 100:
            rows = []
            for b in bars:
                rows.append({
                    "time": b["time"], "open": b["open"], "high": b["high"],
                    "low": b["low"], "close": b["close"],
                    "volume": b.get("volume", 0), "amount": b.get("amount", 0),
                })
            df = pd.DataFrame(rows)
            # 存缓存
            os.makedirs(KLINE_5M_DIR, exist_ok=True)
            df.to_csv(csv_path, index=False)
            # 转标准格式
            df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S")
            df["date"] = df["datetime"].dt.date
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            print(f"  📥 QMT获取5分钟: {full_code} ({len(bars)}根)")
            return df
    except Exception as e:
        pass

    # 3. 从 akshare 获取（覆盖全历史）
    try:
        import akshare as ak
        if full_code.startswith("sh"):
            symbol = f"sh{full_code[2:]}"
        else:
            symbol = f"sz{full_code[2:]}"
        df = ak.stock_zh_a_hist_tx(symbol=symbol, adjust="qfq")
        if df is not None and len(df) > 100:
            # akshare腾讯源返回的5分钟数据需要特定参数
            # 改用 stock_zh_a_hist_min_em 获取分钟数据
            try:
                df_min = ak.stock_zh_a_hist_min_em(
                    symbol=symbol, period="5", start_date="20210618", end_date="20260618", adjust="qfq"
                )
                if df_min is not None and len(df_min) > 100:
                    df_min = df_min.rename(columns={
                        "时间": "time", "开盘": "open", "收盘": "close",
                        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount"
                    })
                    df_min["time"] = pd.to_datetime(df_min["time"]).dt.strftime("%Y%m%d%H%M%S")
                    os.makedirs(KLINE_5M_DIR, exist_ok=True)
                    df_min.to_csv(csv_path, index=False)
                    df_min["datetime"] = pd.to_datetime(df_min["time"], format="%Y%m%d%H%M%S")
                    df_min["date"] = df_min["datetime"].dt.date
                    print(f"  📥 akshare获取5分钟: {full_code} ({len(df_min)}根)")
                    return df_min
            except Exception:
                pass
    except Exception:
        pass

    return None


def resample_to_15min(df_5m: pd.DataFrame) -> Optional[pd.DataFrame]:
    """从5分钟数据合成为15分钟数据"""
    if df_5m is None or df_5m.empty:
        return None
    df = df_5m.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    bars = []
    for _, chunk in df.groupby(pd.Grouper(freq="15min")):
        if chunk.empty:
            continue
        bars.append({
            "datetime": chunk.index[0],
            "open": float(chunk.iloc[0]["open"]),
            "high": float(chunk["high"].max()),
            "low": float(chunk["low"].min()),
            "close": float(chunk.iloc[-1]["close"]),
        })
    if not bars:
        return None
    return pd.DataFrame(bars)


def _check_15min_divergence_upto(df_15m: pd.DataFrame, current_date) -> Optional[float]:
    """滚动窗口的15分钟背驰检查（无前视偏差）"""
    if df_15m is None or len(df_15m) < 60:
        return None
    cutoff = pd.Timestamp(current_date)
    df_upto = df_15m[df_15m["datetime"] < cutoff].copy()
    if len(df_upto) < 60:
        return None
    df_ana = df_upto.set_index("datetime")
    core = ChanlunCore()
    core.process_klines(df_ana)
    core.find_fractals()
    if len(core.fractals) < 4:
        return None
    core.find_bis()
    core.find_zhong_shus()
    core._calc_macd(df_ana["close"].astype(float))
    up_bis = [b for b in core.bis if b.direction == Direction.UP]
    if len(up_bis) < 2:
        return None
    b_prev = up_bis[-2]
    b_curr = up_bis[-1]
    macd_prev = core._macd_at_fractal.get(b_prev.end_fractal.index, 0)
    macd_curr = core._macd_at_fractal.get(b_curr.end_fractal.index, 0)
    if macd_curr < macd_prev and b_curr.high > b_prev.high:
        end_f = b_curr.end_fractal
        for f in core.fractals:
            if f.type == FractalType.TOP and f.index == end_f.index:
                return float(f.third_low)
        return float(end_f.price) * 0.98
    return None


# ═══════════════════════════════════════════════════════════
# 交易成本计算
# ═══════════════════════════════════════════════════════════

def calc_buy_cost(price: float, shares: int) -> Tuple[float, float]:
    amount = price * shares
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    transfer_fee = amount * TRANSFER_FEE_RATE
    total_fee = commission + transfer_fee
    return amount + total_fee, total_fee


def calc_sell_proceeds(price: float, shares: int) -> Tuple[float, float]:
    amount = price * shares
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    stamp_tax = amount * STAMP_TAX_RATE
    transfer_fee = amount * TRANSFER_FEE_RATE
    total_fee = commission + stamp_tax + transfer_fee
    return amount - total_fee, total_fee


def is_uptrend(df_day: pd.DataFrame, cutoff_date=None) -> bool:
    if cutoff_date is not None:
        df_day = df_day[df_day["date"] <= pd.Timestamp(cutoff_date)]
    if len(df_day) < 60:
        return False
    ma20 = df_day["close"].rolling(20).mean()
    ma60 = df_day["close"].rolling(60).mean()
    return ma20.iloc[-1] > ma60.iloc[-1]


# ═══════════════════════════════════════════════════════════
# 缠论信号提取（日线版本）
# ═══════════════════════════════════════════════════════════

def extract_daily_signals(core: ChanlunCore, df: pd.DataFrame) -> Tuple[Dict, Dict]:
    signals = {"buy": [], "sell": []}
    if not core.buy_sell_points:
        return signals, {}
    top_fractal_by_date = {}
    for f in core.fractals:
        if f.type == FractalType.TOP:
            f_date = str(f.timestamp)[:10]
            top_fractal_by_date[f_date] = f
    for p in core.buy_sell_points:
        date_key = str(p.timestamp)[:10]
        if p.type.value in ("buy1", "buy2", "buy3", "secondary_buy"):
            signals["buy"].append({
                "date": pd.Timestamp(p.timestamp),
                "price": p.price,
                "score": 90,
                "type": p.type.value,
            })
        elif p.type.value in ("sell1", "sell2"):
            top_f = top_fractal_by_date.get(date_key)
            third_low = top_f.third_low if top_f else None
            signals["sell"].append({
                "date": pd.Timestamp(p.timestamp),
                "price": p.price,
                "score": 90,
                "type": p.type.value,
                "third_low": third_low,
            })
    confirm_dates = {}
    date_to_idx = {str(row["date"])[:10]: i for i, (_, row) in enumerate(df.iterrows())}
    sorted_dates = sorted(date_to_idx.keys())
    date_to_next = {}
    for idx_d in range(len(sorted_dates) - 1):
        date_to_next[sorted_dates[idx_d]] = sorted_dates[idx_d + 1]
    for f in core.fractals:
        f_date = str(f.timestamp)[:10]
        if f_date in date_to_next:
            confirm_dates[f_date] = date_to_next[f_date]
    return signals, confirm_dates


# ═══════════════════════════════════════════════════════════
# 主回测逻辑
# ═══════════════════════════════════════════════════════════

def run_precise_backtest(stocks: List[Dict], trailing_stop_pct: float = 0.05, no_15min: bool = False) -> Dict:
    print(f"\n🔄 开始精确回测 (支盈30%减半+动态仓位)")

    # 预加载所有股票的数据
    stock_analysis = {}
    total = len(stocks)
    _t0 = datetime.now()
    for idx, s in enumerate(stocks):
        code = s["full_code"]
        if (idx + 1) % 200 == 0:
            elapsed = (datetime.now() - _t0).total_seconds()
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (total - idx - 1) / rate if rate > 0 else 0
            print(f"  日线分析: {idx+1}/{total} ({rate:.0f}只/秒 ETA:{eta/60:.0f}分)", flush=True)
        df_day = load_kline_day(code)
        if df_day is None or len(df_day) < 60:
            continue
        # 日线数据全部读取（不限区间），供 ChanlunCore 完整分析买1/买2/买3
        df_ana = df_day.set_index("date")
        core = ChanlunCore()
        core.process_klines(df_ana)
        core.find_fractals()
        if len(core.fractals) < 4:
            continue
        core.find_bis()
        core.find_zhong_shus()
        if len(df_ana) > 30:
            core._calc_macd(df_ana["close"].astype(float))
        core.find_buy_sell_points()
        signals, confirm_dates = extract_daily_signals(core, df_day)
        stock_analysis[code] = {
            "code": s["code"], "name": s["name"], "full_code": code,
            "df_day": df_day, "df_5m": None,  # 按需延迟加载
            "signals": signals, "confirm_dates": confirm_dates,
        }

    print(f"  加载了 {len(stock_analysis)} 只股票的数据")
    if not stock_analysis:
        print("❌ 没有可用的数据")
        return {}

    # 底分型/顶分型列表
    top_fractal_levels, bottom_fractal_levels = {}, {}
    for code, data in stock_analysis.items():
        cd = data["confirm_dates"]
        df_day = data["df_day"]
        df_ana = df_day.set_index("date")
        for name, ftype, store in [("top", FractalType.TOP, top_fractal_levels),
                                     ("bottom", FractalType.BOTTOM, bottom_fractal_levels)]:
            _core = ChanlunCore()
            _core.process_klines(df_ana)
            _core.find_fractals()
            levels = []
            for f in _core.fractals:
                if f.type == ftype:
                    f_date = str(f.timestamp)[:10]
                    confirm = cd.get(f_date)
                    levels.append({
                        "third_high": f.third_high, "third_low": f.third_low,
                        "confirm_date": confirm, "fractal_date": f_date,
                    })
            if levels:
                store[code] = levels

    # 15分钟K线缓存
    stock_15min = {}
    for code, data in stock_analysis.items():
        df_5m = data.get("df_5m")
        if df_5m is None:
            continue
        df_15m = resample_to_15min(df_5m)
        if df_15m is not None:
            stock_15min[code] = df_15m

    # 诊断信号统计
    total_sell1 = sum(len([s for s in data["signals"]["sell"] if s.get("type") == "sell1"]) for data in stock_analysis.values())
    total_sell2 = sum(len([s for s in data["signals"]["sell"] if s.get("type") == "sell2"]) for data in stock_analysis.values())
    total_buy_sigs = sum(len(data["signals"]["buy"]) for data in stock_analysis.values())
    print(f"  信号统计: {total_buy_sigs} 买入信号, {total_sell1} 一卖信号, {total_sell2} 二卖信号")
    if total_sell1 == 0:
        print(f"  ⚠️ 一卖信号为0")

    all_dates = set()
    for code, data in stock_analysis.items():
        for d in data["df_day"]["date"]:
            all_dates.add(d.date() if hasattr(d, 'date') else d)
    all_dates = sorted([d for d in all_dates if d >= BACKTEST_START.date()])
    print(f"  回测区间: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)}个交易日)")

    # 构建信号优先级索引：类二买>三买>二买
    buy_signal_dates = {}
    for code, data in stock_analysis.items():
        sigs = data.get("signals", {}).get("buy", [])
        date_priority = {}
        for s in sigs:
            d = str(s["date"])[:10] if hasattr(s["date"], "strftime") else str(s["date"])[:10]
            tp = s.get("type", "buy2")
            pri = BUY_SIGNAL_PRIORITY.get(tp, 0)
            # 同一天多个信号取最高优先级
            if d not in date_priority or pri > date_priority[d]:
                date_priority[d] = pri
        if date_priority:
            buy_signal_dates[code] = date_priority

    # ── 回测主循环 ──
    cash = INITIAL_CAPITAL
    no_15min = no_15min
    positions = []
    trades = []
    daily_values = []
    max_peak = INITIAL_CAPITAL
    max_drawdown = 0.0

    # 分型索引初始化
    bottom_fractal_idx = {code: -1 for code in bottom_fractal_levels}
    top_fractal_idx = {code: -1 for code in top_fractal_levels}
    for code in bottom_fractal_levels:
        bottom_fractal_levels[code].sort(key=lambda x: x["fractal_date"])
    for code in top_fractal_levels:
        top_fractal_levels[code].sort(key=lambda x: x["fractal_date"])

    for code, levels in bottom_fractal_levels.items():
        if not levels:
            continue
        df_day = stock_analysis.get(code, {}).get("df_day")
        if df_day is None:
            continue
        start_date = pd.Timestamp(BACKTEST_START.date())
        day_row = df_day[df_day["date"] <= start_date].iloc[-1:] if not df_day[df_day["date"] <= start_date].empty else None
        if day_row is None or day_row.empty:
            continue
        start_low = day_row.iloc[0]["low"]
        found_idx = -1
        for i in range(len(levels) - 1, -1, -1):
            lvl = levels[i]
            if lvl["fractal_date"] > str(BACKTEST_START.date()):
                continue
            if start_low < lvl["third_low"]:
                continue
            else:
                found_idx = i
                break
        bottom_fractal_idx[code] = found_idx

    for code, levels in top_fractal_levels.items():
        if not levels:
            continue
        df_day = stock_analysis.get(code, {}).get("df_day")
        if df_day is None:
            continue
        start_date = pd.Timestamp(BACKTEST_START.date())
        day_row = df_day[df_day["date"] <= start_date].iloc[-1:] if not df_day[df_day["date"] <= start_date].empty else None
        if day_row is None or day_row.empty:
            continue
        start_high = day_row.iloc[0]["high"]
        found_idx = -1
        for i in range(len(levels) - 1, -1, -1):
            lvl = levels[i]
            if lvl["fractal_date"] > str(BACKTEST_START.date()):
                continue
            if start_high > lvl["third_high"]:
                continue
            else:
                found_idx = i
                break
        top_fractal_idx[code] = found_idx

    # ====== 每日主循环 ======
    for date_val in all_dates:
        # 卖出检查 + 止盈检查
        to_remove = []
        for pos in positions:
            if pos.get("bought_today"):
                continue

            code = pos["code"]
            df_5m = stock_analysis.get(code, {}).get("df_5m")
            if df_5m is None:
                continue  # 买入时已确认有5分钟数据，理论上不会到这里

            confirm_dates = stock_analysis.get(code, {}).get("confirm_dates", {})
            bought_date_str = pos["bought_date"].strftime("%Y-%m-%d")
            sell_signals = stock_analysis.get(code, {}).get("signals", {}).get("sell", [])
            active_sell = None
            for sig in sell_signals:
                sig_date = sig["date"].strftime("%Y-%m-%d") if hasattr(sig["date"], "strftime") else str(sig["date"])[:10]
                if sig_date >= bought_date_str and sig.get("type") in ("sell1", "sell2"):
                    sig_confirm = confirm_dates.get(sig_date)
                    if sig_confirm is None or date_val.strftime("%Y-%m-%d") >= sig_confirm:
                        active_sell = sig
                        break

            today_bars = df_5m[df_5m["date"] == date_val]
            should_sell = False
            sell_reason = ""

            # 止损
            stop_loss = pos.get("stop_loss_price")
            if stop_loss and not today_bars.empty:
                day_low = today_bars["low"].min()
                if day_low < stop_loss:
                    should_sell = True
                    sell_reason = "SELL(止损)"

            # ── 主动止盈：浮盈>=30%卖一半 ──
            if not should_sell and not today_bars.empty and not pos.get("tp_done"):
                current_price = today_bars.iloc[-1]["close"]
                unrealized_pnl_pct = (current_price / pos["cost"] - 1) * 100
                if unrealized_pnl_pct >= TAKEPROFIT_PCT * 100:
                    half_shares = pos["shares"] // 2
                    pos["tp_done"] = True
                    if half_shares >= 100:
                        sell_p = round(current_price * (1 - SLIPPAGE), 2)
                        part_proceeds, part_fee = calc_sell_proceeds(sell_p, half_shares)
                        part_cost = pos["total_cost"] * (half_shares / pos["shares"])
                        part_pnl = part_proceeds - part_cost
                        trades.append({
                            "date": date_val, "code": pos["code"],
                            "action": "SELL(止盈30%)", "price": sell_p,
                            "shares": half_shares, "pnl": round(part_pnl, 2),
                            "pnl_pct": round((part_proceeds / part_cost - 1) * 100, 2),
                            "fee": round(part_fee, 2), "proceeds": round(part_proceeds, 2),
                        })
                        cash += part_proceeds
                        pos["shares"] -= half_shares
                        pos["total_cost"] -= part_cost
                        print(f"  💰 止盈减半 {pos['code']} 于¥{sell_p} 释放¥{part_proceeds:.0f} 剩余{pos['shares']}股")

            # 卖点信号(一卖/二卖)
            if not should_sell and active_sell is not None:
                sell_type = active_sell.get("type", "sell1")
                if not today_bars.empty:
                    should_sell = True
                    sell_reason = f"SELL({sell_type})"

            # 15分钟背驰
            if not should_sell and not no_15min:
                df_15m = stock_15min.get(code)
                if df_15m is not None:
                    third_low_15m = _check_15min_divergence_upto(df_15m, date_val)
                    if third_low_15m is not None and not today_bars.empty:
                        for _, bar in today_bars.iterrows():
                            if bar["low"] <= third_low_15m:
                                should_sell = True
                                sell_reason = "SELL(15分背驰跌破)"
                                break

            # 执行卖出（完整清仓）
            if should_sell:
                sell_price = round(today_bars.iloc[0]["open"] * (1 - SLIPPAGE), 2) if not today_bars.empty else 0
                if sell_price > 0 and pos["shares"] > 0:
                    proceeds, fee = calc_sell_proceeds(sell_price, pos["shares"])
                    pnl = proceeds - pos["total_cost"]
                    pnl_pct = (proceeds / pos["total_cost"] - 1) * 100
                    trades.append({
                        "date": date_val, "code": pos["code"],
                        "action": sell_reason, "price": sell_price,
                        "shares": pos["shares"], "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2), "fee": round(fee, 2),
                        "proceeds": round(proceeds, 2),
                        "hold_days": (date_val - pos["bought_date"]).days,
                    })
                    cash += proceeds
                    to_remove.append(pos)

        for pos in to_remove:
            positions.remove(pos)

        # 更新持仓最高价
        for pos in positions:
            if pos["code"] in stock_analysis:
                df_5m = stock_analysis[pos["code"]]["df_5m"]
                day_5m = df_5m[df_5m["date"] == date_val]
                if not day_5m.empty:
                    day_high = day_5m["high"].max()
                    if day_high > pos["highest_price"]:
                        pos["highest_price"] = day_high

        # 更新分型有效性
        for code, levels in bottom_fractal_levels.items():
            if not levels:
                continue
            idx = bottom_fractal_idx[code]
            df_day = stock_analysis.get(code, {}).get("df_day")
            if df_day is None:
                continue
            day_row = df_day[df_day["date"] == pd.Timestamp(date_val)]
            if day_row.empty:
                continue
            day_low = day_row.iloc[0]["low"]
            latest_confirmed_idx = -1
            for i in range(len(levels) - 1, -1, -1):
                lvl = levels[i]
                if lvl["fractal_date"] > str(date_val):
                    continue
                if lvl["confirm_date"] and str(date_val) < lvl["confirm_date"]:
                    continue
                latest_confirmed_idx = i
                break
            if latest_confirmed_idx > idx:
                idx = latest_confirmed_idx
                bottom_fractal_idx[code] = idx
            if idx >= 0 and idx < len(levels):
                current_lvl = levels[idx]
                if day_low < current_lvl["third_low"]:
                    bottom_fractal_idx[code] = idx + 1
                    while bottom_fractal_idx[code] < len(levels):
                        next_lvl = levels[bottom_fractal_idx[code]]
                        if day_low < next_lvl["third_low"]:
                            bottom_fractal_idx[code] += 1
                        else:
                            break
                    if bottom_fractal_idx[code] >= len(levels):
                        bottom_fractal_idx[code] = -1

        for code, levels in top_fractal_levels.items():
            if not levels:
                continue
            idx = top_fractal_idx[code]
            df_day = stock_analysis.get(code, {}).get("df_day")
            if df_day is None:
                continue
            day_row = df_day[df_day["date"] == pd.Timestamp(date_val)]
            if day_row.empty:
                continue
            day_high = day_row.iloc[0]["high"]
            latest_confirmed_idx = -1
            for i in range(len(levels) - 1, -1, -1):
                lvl = levels[i]
                if lvl["fractal_date"] > str(date_val):
                    continue
                if lvl["confirm_date"] and str(date_val) < lvl["confirm_date"]:
                    continue
                latest_confirmed_idx = i
                break
            if latest_confirmed_idx > idx:
                idx = latest_confirmed_idx
                top_fractal_idx[code] = idx
            if idx >= 0 and idx < len(levels):
                current_lvl = levels[idx]
                if day_high > current_lvl["third_high"]:
                    top_fractal_idx[code] = idx + 1
                    while top_fractal_idx[code] < len(levels):
                        next_lvl = levels[top_fractal_idx[code]]
                        if day_high > next_lvl["third_high"]:
                            top_fractal_idx[code] += 1
                        else:
                            break
                    if top_fractal_idx[code] >= len(levels):
                        top_fractal_idx[code] = -1

        # ── 买入：现金驱动，不设持仓上限 ──
        held_codes = {p["code"] for p in positions}
        buy_candidates = []
        for code in bottom_fractal_levels:
            if code in held_codes:
                continue
            if not is_uptrend(stock_analysis[code]["df_day"], date_val):
                continue
            idx = bottom_fractal_idx.get(code, -1)
            if idx < 0 or idx >= len(bottom_fractal_levels[code]):
                continue
            lvl = bottom_fractal_levels[code][idx]
            # 缠论信号过滤+优先级：只买有信号的，记录优先级
            bsd = buy_signal_dates.get(code, {})
            priority = bsd.get(lvl["fractal_date"], 0)
            if priority == 0:
                continue
            if lvl["confirm_date"] and str(date_val) < lvl["confirm_date"]:
                continue
            # 按需拉取5分钟数据
            df_5m = stock_analysis.get(code, {}).get("df_5m")
            if df_5m is None:
                df_5m = fetch_kline_5m(code)
                if df_5m is not None and len(df_5m) >= 100:
                    stock_analysis[code]["df_5m"] = df_5m
                    print(f"  📥 按需获取5分钟: {code} ({len(df_5m)}根)")
            if df_5m is None:
                continue
            today_bars = df_5m[df_5m["date"] == date_val]
            if today_bars.empty:
                continue
            third_high = lvl["third_high"]
            # 成交量过滤：当日成交量必须 > 5日均量的1.5倍（日线级）
            df_day_local = stock_analysis.get(code, {}).get("df_day")
            vol_ok = True
            if df_day_local is not None and "volume" in df_day_local.columns:
                day_row = df_day_local[df_day_local["date"] == pd.Timestamp(date_val)]
                if not day_row.empty:
                    today_vol = float(day_row.iloc[0]["volume"])
                    before = df_day_local[df_day_local["date"] < pd.Timestamp(date_val)]
                    avg5 = before["volume"].tail(5).mean()
                    if avg5 > 0 and today_vol < avg5 * VOLUME_RATIO:
                        vol_ok = False  # 成交量不足，跳过
            for _, bar in today_bars.iterrows():
                if bar["high"] > third_high and vol_ok:
                    buy_price = round(bar["open"] * (1 + SLIPPAGE), 2)
                    if buy_price > third_high * 1.05:
                        continue  # 涨幅超过5个点
                    max_shares = int(cash / buy_price / 100) * 100
                    if max_shares >= 100:
                        total_cost, fee = calc_buy_cost(buy_price, max_shares)
                        if total_cost <= cash:
                            buy_candidates.append({
                                "code": code, "price": buy_price,
                                "shares": max_shares, "cost": total_cost,
                                "fee": fee, "third_low": lvl["third_low"],
                                "third_high": lvl["third_high"],
                                "name": stock_analysis[code]["name"],
                                "priority": priority,
                            })
                    break

        # 按评分排序，依次买入（用所有可用现金）
        if buy_candidates:
            # 按 strategy_config.BUY_SIGNAL_PRIORITY 排序
            buy_candidates.sort(key=lambda x: -x["priority"])
            for cand in buy_candidates:
                if cash < cand["price"] * 100:
                    continue
                max_shares = int(cash / cand["price"] / 100) * 100
                if max_shares < 100:
                    continue
                total_cost, fee = calc_buy_cost(cand["price"], max_shares)
                if total_cost > cash:
                    continue
                cash -= total_cost
                positions.append({
                    "code": cand["code"], "name": cand["name"],
                    "shares": max_shares, "cost": cand["price"],
                    "total_cost": total_cost, "highest_price": cand["price"],
                    "top_high": cand["price"], "bought_date": date_val,
                    "bought_bar_idx": 0,
                    "stop_loss_price": (cand["third_high"] + cand["third_low"]) / 2
                    if (cand["third_high"] - cand["third_low"]) / cand["third_high"] > 0.05
                    else cand["third_low"],
                    "bought_today": True, "tp_done": False,
                })
                sig_type = {3: "类二买", 2: "三买", 1: "二买"}.get(cand["priority"], "二买")
                trades.append({
                    "date": date_val, "code": cand["code"],
                    "action": f"BUY({sig_type})", "price": cand["price"],
                    "shares": max_shares, "pnl": 0, "pnl_pct": 0,
                    "fee": round(fee, 2),
                })
                if cash < cand["price"] * 100:
                    break

        # 记录每日净值
        position_value = 0.0
        for pos in positions:
            if pos["code"] in stock_analysis:
                df_5m = stock_analysis[pos["code"]]["df_5m"]
                day_5m = df_5m[df_5m["date"] == date_val]
                if not day_5m.empty:
                    position_value += pos["shares"] * day_5m.iloc[-1]["close"]
        portfolio_value = cash + position_value
        daily_values.append({
            "date": date_val, "value": round(portfolio_value, 2),
            "cash": round(cash, 2), "position_value": round(position_value, 2),
        })
        if portfolio_value > max_peak:
            max_peak = portfolio_value
        dd = (max_peak - portfolio_value) / max_peak * 100
        if dd > max_drawdown:
            max_drawdown = dd

        # T+1 标记翻转
        for pos in positions:
            if pos.get("bought_today"):
                pos["bought_today"] = False

    # 强制清仓
    for pos in positions[:]:
        if pos["code"] in stock_analysis:
            last_row = stock_analysis[pos["code"]]["df_5m"].iloc[-1]
            sell_price = round(last_row["close"] * (1 - SLIPPAGE), 2)
            if pos["shares"] > 0:
                proceeds, fee = calc_sell_proceeds(sell_price, pos["shares"])
                pnl = proceeds - pos["total_cost"]
                trades.append({
                    "date": all_dates[-1] if all_dates else date_val,
                    "code": pos["code"], "action": "SELL(清仓)",
                    "price": sell_price, "shares": pos["shares"],
                    "pnl": round(pnl, 2), "fee": round(fee, 2),
                })
                cash += proceeds
                positions.remove(pos)

    # 计算绩效
    final_value = cash
    total_return = (final_value / INITIAL_CAPITAL - 1) * 100
    sell_trades = [t for t in trades if t["action"].startswith("SELL")]
    full_sells = [t for t in sell_trades if "止盈" not in t["action"]]
    win_trades = [t for t in full_sells if t.get("pnl", 0) > 0]
    loss_trades = [t for t in full_sells if t.get("pnl", 0) <= 0]
    win_rate = len(win_trades) / len(full_sells) * 100 if full_sells else 0
    avg_hold_days = 0

    return {
        "trailing_stop_pct": trailing_stop_pct,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "total_trades": len(trades),
        "win_trades": len(win_trades),
        "loss_trades": len(loss_trades),
        "win_rate": round(win_rate, 1),
        "avg_hold_days": round(avg_hold_days, 1),
        "trades": trades,
        "daily_values": daily_values,
    }


# ═══════════════════════════════════════════════════════════
# 结果保存
# ═══════════════════════════════════════════════════════════

def save_results(result: Dict):
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    import csv

    trades_path = output_dir / "trades.csv"
    with open(trades_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "direction", "price", "quantity", "pnl", "reason", "code", "signal_type"])
        for t in result.get("trades", []):
            is_buy = t["action"].startswith("BUY")
            direction = "BUY" if is_buy else "SELL"
            reason = t["action"] if not is_buy else ""
            code = t.get("code", t.get("name", ""))
            sig_type = t["action"].replace("BUY(", "").replace(")", "") if is_buy and "(" in t["action"] else ""
            writer.writerow([str(t["date"]), direction, t["price"], t["shares"],
                            round(t.get("pnl", 0), 2), reason, code, sig_type])

    equity_path = output_dir / "equity_daily.csv"
    with open(equity_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "equity", "cash", "position_value"])
        for d in result.get("daily_values", []):
            writer.writerow([str(d["date"]), d["value"], d.get("cash", 0), d.get("position_value", 0)])

    params_path = output_dir / "parameters.yaml"
    with open(params_path, "w", encoding="utf-8") as f:
        f.write(f"strategy_version: v2_takeprofit_1.0\n")
        f.write(f"start_date: {BACKTEST_START.strftime('%Y-%m-%d')}\n")
        f.write(f"end_date: {BACKTEST_END.strftime('%Y-%m-%d')}\n")
        f.write(f"initial_capital: {INITIAL_CAPITAL}\n")
        f.write(f"takeprofit_pct: {TAKEPROFIT_PCT}\n")
        f.write(f"commission_rate: {COMMISSION_RATE}\n")
        f.write(f"min_commission: {MIN_COMMISSION}\n")
        f.write(f"stamp_tax_rate: {STAMP_TAX_RATE}\n")
        f.write(f"transfer_fee_rate: {TRANSFER_FEE_RATE}\n")
        f.write(f"slippage: {SLIPPAGE}\n")

    source_path = output_dir / "data_source.yaml"
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(f"provider: local_cache\n")
        f.write(f"start: 2024-12-02\n")
        f.write(f"end: {BACKTEST_END.strftime('%Y-%m-%d')}\n")
        f.write(f"adjusted: true\n")

    print(f"\n💾 结果已保存: {output_dir}")
    return output_dir


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="主动止盈30%减半+动态仓位")
    parser.add_argument("--no-verify", action="store_true", help="跳过验证器")
    args = parser.parse_args()

    print("=" * 65)
    print("  🚀 变体2: 止盈30%减半 + 动态仓位管理")
    print("  规则: 全仓进 → 浮盈30%减半 → 释放现金继续买入")
    print("=" * 65)

    stocks = load_all_stocks()
    if not stocks:
        print("❌ 没有可回测的股票")
        return

    result = run_precise_backtest(stocks)

    print("\n" + "=" * 65)
    print("  📊 回测结果")
    print("=" * 65)
    print(f"  总收益率: {result['total_return_pct']:+.2f}%")
    print(f"  最大回撤: {result['max_drawdown_pct']:.2f}%")
    print(f"  交易次数: {result['total_trades']}")
    print("=" * 65)

    out_dir = save_results(result)
    if not args.no_verify:
        import subprocess
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "verify_backtest.py"),
            "--trades", str(out_dir / "trades.csv"),
            "--equity", str(out_dir / "equity_daily.csv"),
            "--params", str(out_dir / "parameters.yaml"),
            "--source", str(out_dir / "data_source.yaml"),
        ]
        print(f"\n🔍 运行验证器...")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        print(proc.stderr)
        print(proc.stdout)
        if proc.returncode != 0:
            print(f"❌ 验证失败: returncode={proc.returncode}")
        else:
            print(f"✅ 验证通过 ({len(result.get('trades', []))} 笔交易)")

    # 深度分析
    trades_list = result.get("trades", [])
    from collections import defaultdict
    stock_stats = defaultdict(lambda: {"pnl": 0.0, "sells": 0, "wins": 0, "losses": 0})
    for t in trades_list:
        code = t.get("code", "?")
        if t["action"].startswith("SELL"):
            p = t.get("pnl", 0)
            stock_stats[code]["pnl"] += p
            stock_stats[code]["sells"] += 1
            if p > 0:
                stock_stats[code]["wins"] += 1
            else:
                stock_stats[code]["losses"] += 1

    analysis = {
        "stock_breakdown": [
            {"code": c, "pnl": round(d["pnl"], 2), "trades": d["sells"],
             "wins": d["wins"], "losses": d["losses"],
             "avg_per_trade": round(d["pnl"] / d["sells"], 2) if d["sells"] else 0}
            for c, d in sorted(stock_stats.items(), key=lambda x: -abs(x[1]["pnl"]))
        ],
        "concentration": {},
        "monthly_returns": [],
    }
    analysis_path = out_dir / "analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"💾 深度分析已保存: {analysis_path}")


if __name__ == "__main__":
    main()
