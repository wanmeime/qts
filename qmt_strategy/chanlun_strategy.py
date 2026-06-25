# -*- coding: utf-8 -*-
"""
QMT 缠论交易策略 - 模拟盘验证
================================
策略逻辑（根据用户实战交易系统）：
  1. 选股：热点板块（AI/CPO/PCB/机器人/半导体/存储/钻石）→ 盈利股 → 低PE优先
  2. 买入：日线底分型突破 third_high 瞬间买入（二买/类二买）
  3. 卖出：日线二卖（反弹不过前高+拐头向下）
  4. 止损：买入价下方约2%（突破失败离场）
  5. 仓位：全仓进出，T+1

使用方法：
  在 QMT 程序化交易中导入此策略

依赖：
  - xtquant (QMT自带)
  - 需将 qmt_strategy/ 目录放入 QMT 的策略路径
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import sys, os, json
from pathlib import Path

# ── 同目录下的缠论核心模块（需放在QMT策略目录下）──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from chanlun_core_simple import ChanlunCoreSimple, find_bottom_breakout, find_top_erMai
    SIMPLE_MODE = True
except ImportError:
    SIMPLE_MODE = False
    print("[策略] 未找到简化缠论模块，将使用xtquant内置计算")


# ════════════════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════════════════

# 热点板块自选股（AI/CPO/PCB/机器人/半导体/存储/钻石——用户指定的半年热点）
HOT_STOCKS = {
    # ── AI / CPO / 光模块 ──
    "300502": "新易盛",      # CPO龙头
    "300308": "中际旭创",     # CPO/光模块
    "300394": "天孚通信",     # CPO
    "300620": "光库科技",     # CPO
    "688100": "威胜信息",     # AI算力
    "688981": "中芯国际",     # 半导体
    # ── PCB ──
    "002463": "沪电股份",     # PCB龙头
    "603119": "浙江荣泰",     # PCB
    "002938": "鹏鼎控股",     # PCB
    "300476": "胜宏科技",     # PCB
    # ── 机器人 ──
    "300124": "汇川技术",     # 机器人/工控
    "002527": "新时达",       # 机器人
    "300024": "机器人",       # 机器人
    "688160": "步科股份",     # 机器人
    # ── AI设备 ──
    "601138": "工业富联",     # AI服务器
    "000977": "浪潮信息",     # AI服务器
    "300750": "宁德时代",     # AI设备/储能
    "002594": "比亚迪",       # AI设备
    # ── 半导体/存储 ──
    "300666": "江丰电子",     # 半导体材料
    "688012": "中微公司",     # 半导体设备
    "002371": "北方华创",     # 半导体设备
    "603986": "兆易创新",     # 存储芯片
    "300661": "圣邦股份",     # 模拟芯片
    "300604": "长川科技",     # 半导体测试
    "688008": "澜起科技",     # 内存接口
    # ── 钻石 ──
    "002130": "沃尔核材",     # 培育钻石
    "300179": "四方达",       # 培育钻石
    "000657": "中钨高新",     # 钻石
}

INITIAL_CAPITAL = 10000        # 初始资金1万
COMMISSION_RATE = 0.00025      # 佣金万2.5
MIN_COMMISSION = 5.0           # 最低佣金5元
STAMP_TAX_RATE = 0.0005        # 印花税万5
SLIPPAGE_BUY = 0.10            # 买入余量：third_high + 0.10
STOP_LOSS_OFFSET = 0.10        # 止损：third_high - 0.10
MIN_KLINE_DAYS = 60            # 最少需要60天K线数据做缠论分析

# ════════════════════════════════════════════════════════════
# 策略核心（QMT handlebar）
# ════════════════════════════════════════════════════════════

class ChanlunQMTStrategy:
    """QMT缠论交易策略封装"""

    def __init__(self):
        self.stock_pool = list(HOT_STOCKS.keys())
        self.stock_names = HOT_STOCKS
        self.position = None       # 当前持仓 {code, shares, buy_price, stop_loss}
        self.bought_today = False  # T+1标记
        self.trade_log = []        # 交易记录
        self.capital = INITIAL_CAPITAL
        self.last_check_date = None
        self.signal_cache = {}     # 信号缓存 {code: {buy_signals, sell_signals}}

    def on_init(self, context_info):
        """QMT init 回调"""
        print(f"[策略] 初始化: {len(self.stock_pool)}只热点股, 资金{self.capital}")

    def on_bar(self, context_info):
        """QMT handlebar 回调 - 每根K线调用"""
        # 获取当前日期和时间
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 每天只检查一次
        if self.last_check_date == today:
            return
        self.last_check_date = today

        # 获取当前持仓
        self._sync_position(context_info)

        # T+1：今天买的不能卖
        if self.position and self.bought_today:
            self.bought_today = False
            return

        # 持仓中：检查卖出信号
        if self.position:
            self._check_sell(context_info, today)

        # 空仓：检查买入信号
        if not self.position:
            self._check_buy(context_info, today)

    def _sync_position(self, ctx):
        """从QMT同步当前持仓（模拟盘模式下用本地变量）"""
        # 在真实QMT中，这里应该调用 get_position()
        pass

    def _fetch_kline(self, ctx, code: str, days: int = 120):
        """从QMT获取日K线数据"""
        try:
            qmt_code = f"{code}.SZ" if code.startswith(("0", "3")) else f"{code}.SH"
            data = ctx.get_market_data_ex(
                field_list=[],
                stock_list=[qmt_code],
                period="1d",
                count=days + 30,
                dividend_type="front",
            )
            if qmt_code in data and len(data[qmt_code]) > 0:
                df = data[qmt_code]
                df = df.reset_index()
                df = df.rename(columns={"index": "date"})
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.tail(days)
        except Exception as e:
            print(f"  [数据] {code} 获取失败: {e}")
        return None

    def _check_buy(self, ctx, today):
        """检查买入信号"""
        candidates = []

        for code in self.stock_pool:
            # 获取K线
            df = self._fetch_kline(ctx, code, MIN_KLINE_DAYS)
            if df is None or len(df) < 30:
                continue

            # 缠论分析
            if SIMPLE_MODE:
                signal = find_bottom_breakout(df)
            else:
                signal = self._simple_breakout_check(df)

            if signal:
                candidates.append({
                    "code": code,
                    "name": self.stock_names.get(code, code),
                    "third_high": signal["third_high"],
                    "buy_price": round(signal["third_high"] + SLIPPAGE_BUY, 2),
                    "stop_loss": round(signal["third_high"] - STOP_LOSS_OFFSET, 2),
                    "score": signal.get("score", 90),
                })

        if not candidates:
            return

        # 选评分最高的
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        buy_price = best["buy_price"]
        shares = int(self.capital / buy_price / 100) * 100

        if shares < 100:
            return

        # 执行买入
        print(f"\n🚀 [买入] {best['name']}({best['code']}) "
              f"价格={buy_price} 股数={shares} "
              f"止损={best['stop_loss']}")

        self.position = {
            "code": best["code"],
            "name": best["name"],
            "shares": shares,
            "buy_price": buy_price,
            "cost": buy_price * shares + self._calc_fee(buy_price, shares, True),
            "stop_loss": best["stop_loss"],
        }
        self.bought_today = True
        self.capital -= self.position["cost"]

        self.trade_log.append({
            "date": today, "code": best["code"], "name": best["name"],
            "action": "BUY", "price": buy_price, "shares": shares,
        })

    def _check_sell(self, ctx, today):
        """检查卖出信号"""
        pos = self.position
        code = pos["code"]

        # 1. 紧止损检查
        df = self._fetch_kline(ctx, code, 10)
        if df is not None and len(df) > 0:
            today_low = float(df.iloc[-1]["low"])
            if today_low <= pos["stop_loss"]:
                self._execute_sell(ctx, today, "止损-突破失败")
                return

        # 2. 二卖检查（反弹不过前高）
        df_long = self._fetch_kline(ctx, code, MIN_KLINE_DAYS)
        if df_long is not None:
            if SIMPLE_MODE:
                sell_signal = find_top_erMai(df_long)
            else:
                sell_signal = self._simple_erMai_check(df_long)

            if sell_signal:
                self._execute_sell(ctx, today, "二卖-反弹不过前高")

    def _execute_sell(self, ctx, today, reason):
        """执行卖出"""
        pos = self.position
        df = self._fetch_kline(ctx, pos["code"], 5)
        if df is None or len(df) == 0:
            return

        sell_price = float(df.iloc[-1]["close"])
        proceeds, fee = self._calc_sell(sell_price, pos["shares"])
        pnl = proceeds - pos["cost"]
        pnl_pct = (proceeds / pos["cost"] - 1) * 100

        print(f"  💰 [卖出] {pos['name']}({pos['code']}) "
              f"价格={sell_price:.2f} 盈亏={pnl:+.0f}({pnl_pct:+.1f}%) [{reason}]")

        self.capital += proceeds
        self.trade_log.append({
            "date": today, "code": pos["code"], "name": pos["name"],
            "action": "SELL", "price": sell_price, "shares": pos["shares"],
            "pnl": round(pnl, 2), "reason": reason,
        })
        self.position = None

    def _calc_fee(self, price, shares, is_buy):
        """计算交易费用"""
        amount = price * shares
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        transfer = amount * 0.00001
        total = commission + transfer
        if not is_buy:
            total += amount * STAMP_TAX_RATE
        return total

    def _calc_sell(self, price, shares):
        """计算卖出所得"""
        amount = price * shares
        fee = self._calc_fee(price, shares, False)
        return amount - fee, fee

    def _simple_breakout_check(self, df):
        """简化版底分型突破检测（当无chanlun_core时使用）"""
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        n = len(closes)
        if n < 10:
            return None

        # 找最近的一个底分型（三根K线：中间最低）
        for i in range(n - 4, 2, -1):
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                third_high = highs[i+1]
                # 检查当前价格是否突破第三根K线高点
                if closes[-1] > third_high:
                    return {"third_high": third_high, "score": 85}
                break
        return None

    def _simple_erMai_check(self, df):
        """简化版二卖检测"""
        highs = df["high"].values
        closes = df["close"].values
        n = len(highs)
        if n < 20:
            return None

        # 找最近的两个显著高点
        peaks = []
        for i in range(5, n - 5):
            if highs[i] == max(highs[i-5:i+6]):
                peaks.append((i, highs[i]))

        if len(peaks) >= 2:
            p1_idx, p1_h = peaks[-2]
            p2_idx, p2_h = peaks[-1]
            # 第二高点低于第一高点 = 反弹失败
            if p2_h < p1_h and p2_idx > p1_idx:
                # 检查当前价格是否已跌破第二高点附近
                current = closes[-1]
                recent_low = min(highs[p2_idx:p2_idx+5]) if p2_idx+5 < n else closes[-1]
                if current < p2_h * 0.98:
                    return {"sell_price": p2_h, "score": 90}
        return None


# ════════════════════════════════════════════════════════════
# QMT 策略入口
# ════════════════════════════════════════════════════════════

_strategy = ChanlunQMTStrategy()


def init(ContextInfo):
    """QMT策略初始化"""
    _strategy.on_init(ContextInfo)


def handlebar(ContextInfo):
    """QMT策略主循环"""
    _strategy.on_bar(ContextInfo)
