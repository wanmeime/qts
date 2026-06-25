# -*- coding: utf-8 -*-
"""
QMT 模拟盘验证策略
====================
热点板块自选股 + 缠论买卖点信号

选股范围（2026年上半年A股热点板块）：
  - AI/CPO/光模块：新易盛、中际旭创、天孚通信、光库科技
  - PCB：沪电股份、鹏鼎控股、胜宏科技
  - 机器人：汇川技术、新时达、机器人
  - AI设备：工业富联、浪潮信息
  - 半导体：中芯国际、北方华创、中微公司、兆易创新
  - 存储芯片：澜起科技
  - 培育钻石：四方达、中钨高新、沃尔核材
"""

# ════════════════════════════════════════════════════════════
# 导入
# ════════════════════════════════════════════════════════════
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json, os, sys
from pathlib import Path

# 在当前目录下找简化缠论模块
sys.path.insert(0, os.path.dirname(__file__))
from chanlun_core_simple import find_bottom_breakout, find_top_erMai


# ════════════════════════════════════════════════════════════
# QMT 策略入
# ════════════════════════════════════════════════════════════

# 热点板块股票池
HOT_STOCKS = {
    # ── AI / CPO / 光模块 ──
    "300502.SZ": "新易盛",
    "300308.SZ": "中际旭创",
    "300394.SZ": "天孚通信",
    # ── PCB ──
    "002463.SZ": "沪电股份",
    "002938.SZ": "鹏鼎控股",
    "300476.SZ": "胜宏科技",
    # ── 机器人 ──
    "300124.SZ": "汇川技术",
    "300024.SZ": "机器人",
    # ── AI设备 ──
    "601138.SH": "工业富联",
    "000977.SZ": "浪潮信息",
    "002594.SZ": "比亚迪",
    # ── 半导体 ──
    "688981.SH": "中芯国际",
    "002371.SZ": "北方华创",
    "603986.SH": "兆易创新",
    "300604.SZ": "长川科技",
    "688008.SH": "澜起科技",
    "300666.SZ": "江丰电子",
    # ── 培育钻石 ──
    "002130.SZ": "沃尔核材",
    "300179.SZ": "四方达",
    "000657.SZ": "中钨高新",
}

STOP_LOSS_TICKS = 0.10         # 止损：third_high 下方0.10
BUY_SLIPPAGE = 0.10            # 买入余量：third_high + 0.10

# ── 全局状态 ──
_position = None       # {code, shares, buy_price, stop_loss, cost}
_bought_today = False
_capital = 10000
_trade_log = []
_last_check = ""


def init(ContextInfo):
    """QMT 策略初始化（只调用一次）"""
    global _capital, _trade_log
    
    print("=" * 50)
    print(f"  热点板块缠论策略 v1")
    print(f"  股票池: {len(HOT_STOCKS)} 只")
    print(f"  起始资金: {_capital}")
    print("=" * 50)
    
    ContextInfo.set_field_name("1d")  # 日线级别


def handlebar(ContextInfo):
    """QMT 策略主循环（每根K线调用一次）"""
    global _position, _bought_today, _capital, _trade_log, _last_check

    today = datetime.now().strftime("%Y-%m-%d")
    
    # 每天只检查一次
    if _last_check == today:
        return
    _last_check = today

    # ── T+1 ──
    if _position and _bought_today:
        _bought_today = False
        return

    # ── 持仓中：检查卖出 ──
    if _position:
        code = _position["code"]
        df = _get_kline(ContextInfo, code, 60)
        if df is None:
            return

        # 1. 紧止损
        today_low = float(df["low"].iloc[-1])
        if today_low <= _position["stop_loss"]:
            _sell(ContextInfo, df, "止损-突破失败")
            return

        # 2. 二卖（反弹不过前高）
        sell_sig = find_top_erMai(df)
        if sell_sig:
            _sell(ContextInfo, df, "二卖-反弹不过前高")
            return

    # ── 空仓：检查买入 ──
    if not _position:
        candidates = []
        for qmt_code, name in HOT_STOCKS.items():
            df = _get_kline(ContextInfo, qmt_code, 60)
            if df is None:
                continue

            buy_sig = find_bottom_breakout(df)
            if buy_sig:
                candidates.append({
                    "code": qmt_code,
                    "name": name,
                    "third_high": buy_sig["third_high"],
                    "score": buy_sig["score"],
                })

        if candidates:
            candidates.sort(key=lambda x: x["score"], reverse=True)
            best = candidates[0]
            buy_price = round(best["third_high"] + BUY_SLIPPAGE, 2)
            shares = int(_capital / buy_price / 100) * 100

            if shares >= 100:
                _buy(ContextInfo, best["code"], best["name"], buy_price, shares)
                print(f"  >> 买入 {best['name']} {buy_price}×{shares}")


def _get_kline(ContextInfo, code: str, count: int = 60):
    """从 QMT 获取日K线"""
    try:
        data = ContextInfo.get_market_data_ex(
            field_list=[],
            stock_list=[code],
            period="1d",
            count=count + 20,
            dividend_type="front",
        )
        if code in data and len(data[code]) > 0:
            df = data[code].copy()
            return df.tail(count)
    except:
        pass
    return None


def _buy(ContextInfo, code, name, price, shares):
    """执行买入"""
    global _position, _bought_today, _capital, _trade_log
    
    fee = _calc_fee(price, shares, True)
    cost = price * shares + fee
    stop_loss = price - STOP_LOSS_TICKS - 0.10  # third_high 기준

    if cost > _capital:
        return

    _capital -= cost
    _position = {
        "code": code, "name": name,
        "shares": shares, "buy_price": price,
        "cost": cost, "stop_loss": stop_loss,
    }
    _bought_today = True
    _trade_log.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "code": code, "name": name,
        "action": "BUY", "price": price, "shares": shares,
    })


def _sell(ContextInfo, df, reason):
    """执行卖出"""
    global _position, _capital, _trade_log
    
    if _position is None:
        return

    close = float(df["close"].iloc[-1])
    proceeds, fee = _calc_sell(close, _position["shares"])
    pnl = proceeds - _position["cost"]
    pnl_pct = (proceeds / _position["cost"] - 1) * 100

    print(f"  << 卖出 {_position['name']} {close:.2f} "
          f"盈亏{pnl:+.0f}({pnl_pct:+.1f}%) [{reason}]")

    _capital += proceeds
    _trade_log.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "code": _position["code"],
        "name": _position["name"],
        "action": "SELL", "price": close,
        "shares": _position["shares"],
        "pnl": round(pnl, 2), "reason": reason,
    })
    _position = None


def _calc_fee(price, shares, is_buy):
    """计算费用"""
    amount = price * shares
    comm = max(amount * 0.00025, 5.0)
    transfer = amount * 0.00001
    total = comm + transfer
    if not is_buy:
        total += amount * 0.0005  # 印花税
    return total


def _calc_sell(price, shares):
    """卖出计算"""
    amount = price * shares
    fee = _calc_fee(price, shares, False)
    return amount - fee, fee
