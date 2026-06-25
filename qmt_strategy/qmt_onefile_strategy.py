# -*- coding: gb2312 -*-
# QMT Chanlun Strategy v1 - Hot Sectors + Chanlun Signals
import numpy as np
import pandas as pd
from datetime import datetime

# Hot sector stocks (AI/CPO/PCB/Robots/Semiconductors/Diamonds)
STOCKS = {
    "300502.SZ": "XinYiSheng", "300308.SZ": "ZhongJiXuChuang",
    "300394.SZ": "TianFuTongXin", "002463.SZ": "HuDianGuFen",
    "300476.SZ": "ShengHongKeJi", "300124.SZ": "HuiChuanJiShu",
    "300024.SZ": "JiQiRen", "601138.SH": "GongYeFuLian",
    "000977.SZ": "LangChaoXinXi", "002594.SZ": "BiYaDi",
    "603986.SH": "ZhaoYiChuangXin", "688008.SH": "LanQiKeJi",
    "300666.SZ": "JiangFengDianZi", "002371.SZ": "BeiFangHuaChuang",
    "002130.SZ": "WoErHeCai", "300179.SZ": "SiFangDa",
}

# State
g_pos = None
g_lock = False
g_cash = 10000
g_last = ""


def init(C):
    print("[Strategy] Chanlun Strategy Started. Stocks:", len(STOCKS))


def handlebar(C):
    global g_pos, g_lock, g_cash, g_last
    
    today = datetime.now().strftime("%Y-%m-%d")
    if today == g_last: return
    g_last = today

    # T+1 lock
    if g_pos and g_lock:
        g_lock = False
        return

    # Check sell
    if g_pos:
        df = _kline(C, g_pos["code"], 60)
        if df is not None:
            if df["low"].iloc[-1] <= g_pos["stop_loss"]:
                _sell(C, df, "StopLoss")
                return
            if _ermai(df):
                _sell(C, df, "Sell2")
                return
        return

    # Check buy
    cand = []
    for code in STOCKS:
        df = _kline(C, code, 60)
        if df is None: continue
        sig = _bottom_breakout(df)
        if sig:
            cand.append({"code": code, "price": round(sig + 0.10, 2), "stop": round(sig - 0.10, 2)})
    
    if not cand: return
    best = cand[0]
    shares = int(g_cash / best["price"] / 100) * 100
    if shares < 100: return
    
    cost = best["price"] * shares + _fee(best["price"], shares, True)
    if cost > g_cash: return
    
    g_cash -= cost
    g_pos = {"code": best["code"], "shares": shares, "cost": cost, "stop_loss": best["stop"]}
    g_lock = True
    print(f"  BUY {best['code']} {best['price']}x{shares}")


def _kline(C, code, n):
    try:
        d = C.get_market_data_ex(field_list=[], stock_list=[code], period="1d", count=n+20, dividend_type="front")
        return d[code].tail(n) if code in d and len(d[code]) > 0 else None
    except: return None


def _bottom_breakout(df):
    """Detect bottom fractal breakout - buy signal"""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    n = len(c)
    for i in range(n-3, 1, -1):
        if l[i] < l[i-1] and l[i] < l[i+1] and c[-1] > h[i+1]:
            return float(h[i+1])
    return None


def _ermai(df):
    """Detect sell2: failed bounce after a top"""
    h = df["high"].values
    n = len(h)
    peaks = []
    for i in range(5, n-5):
        if h[i] == max(h[i-5:i+6]):
            peaks.append((i, h[i]))
    if len(peaks) < 2: return None
    p1, p2 = peaks[-2], peaks[-1]
    return (p2[1] < p1[1] and p2[0] - p1[0] >= 5)


def _fee(price, shares, buy):
    a = price * shares
    c = max(a * 0.00025, 5.0)
    t = c + a * 0.00001
    if not buy: t += a * 0.0005
    return t


def _sell(C, df, reason):
    global g_pos, g_cash
    p = float(df["close"].iloc[-1])
    r = p * g_pos["shares"] - _fee(p, g_pos["shares"], False)
    pnl = r - g_pos["cost"]
    print(f"  SELL {g_pos['code']} {p:.2f} PnL{pnl:+.0f} [{reason}]")
    g_cash += r
    g_pos = None
