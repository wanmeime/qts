# -*- coding: utf-8 -*-
"""
莲花控股 (600186) 缠论分析 - 使用新浪财经API数据
"""
import json
import subprocess
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chanlun_core import ChanlunCore, Direction, BuySellType, FractalType

# ============================================================
# 1. 从新浪财经API获取日K线数据
# ============================================================
print("=" * 60)
print("莲花控股 (sh600186) 缠论分析")
print("=" * 60)

cmd = [
    "curl", "-s",
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600186&scale=240&ma=no&datalen=100"
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
raw_data = json.loads(result.stdout)

df = pd.DataFrame(raw_data)
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df['day'] = pd.to_datetime(df['day'])
df.set_index('day', inplace=True)
df.sort_index(inplace=True)

print(f"\n数据范围: {df.index[0].date()} ~ {df.index[-1].date()}")
print(f"数据量: {len(df)} 根K线")
print(f"最新价: {df['close'].iloc[-1]:.2f} ({df.index[-1].date()})")

# ============================================================
# 2. 缠论核心分析
# ============================================================
core = ChanlunCore()
analysis = core.analyze(df)

print(f"\n处理后K线: {analysis['klines']} 根")
print(f"分型: {analysis['fractals']} 个")
print(f"笔: {analysis['bis']} 个")
print(f"中枢: {analysis['zhong_shus']} 个")
print(f"买卖点: {len(analysis['buy_sell_points'])} 个")

# ============================================================
# 3. 详细输出
# ============================================================

# --- 笔 ---
print("\n" + "-" * 60)
print("【笔】")
for i, bi in enumerate(core.bis):
    d = "UP" if bi.direction == Direction.UP else "DN"
    print(f"  笔{i+1}: {d} [{bi.start_fractal.timestamp}~{bi.end_fractal.timestamp}] "
          f"{bi.start_fractal.price:.2f} -> {bi.end_fractal.price:.2f}")

# --- 中枢 ---
print("\n" + "-" * 60)
print("【中枢】")
for i, zs in enumerate(core.zhong_shus):
    print(f"  中枢{i+1}: [{zs.low:.2f}, {zs.high:.2f}] 含{len(zs.bis)}笔")

# --- 买卖点 ---
print("\n" + "-" * 60)
print("【买卖点】")
for bp in analysis['buy_sell_points']:
    label = "买入" if "buy" in bp.type.value else "卖出"
    print(f"  {bp.type.value}: {bp.price:.2f} ({bp.timestamp}) [{label}]")

# ============================================================
# 4. 趋势判断与操作建议
# ============================================================
current_price = float(df['close'].iloc[-1])
current_bi = core.bis[-1] if core.bis else None
current_bi_dir = analysis['current_bi_direction']
in_zs = analysis['in_zhongshu']
trend = analysis['trend']

# 最近买卖点
buy_points = [p for p in analysis['buy_sell_points'] if 'buy' in p.type.value]
sell_points = [p for p in analysis['buy_sell_points'] if 'sell' in p.type.value]
latest_buy = buy_points[-1] if buy_points else None
latest_sell = sell_points[-1] if sell_points else None

# 最近中枢
latest_zs = core.zhong_shus[-1] if core.zhong_shus else None

print("\n" + "=" * 60)
print("【综合分析报告】")
print("=" * 60)

print(f"\n当前价格: {current_price:.2f}")
print(f"当前笔方向: {'上涨' if current_bi_dir == Direction.UP else '下跌' if current_bi_dir == Direction.DOWN else '未知'}")
print(f"是否在中枢中: {'是' if in_zs else '否'}")
print(f"整体趋势: {trend}")

if latest_zs:
    print(f"\n最近中枢: [{latest_zs.low:.2f}, {latest_zs.high:.2f}]")
    mid = (latest_zs.high + latest_zs.low) / 2
    print(f"  中枢中点: {mid:.2f}")
    if current_price > latest_zs.high:
        print(f"  当前价在中枢上方 ({current_price:.2f} > {latest_zs.high:.2f})")
    elif current_price < latest_zs.low:
        print(f"  当前价在中枢下方 ({current_price:.2f} < {latest_zs.low:.2f})")
    else:
        print(f"  当前价在中枢内")

if latest_buy:
    print(f"\n最近买点: {latest_buy.type.value} = {latest_buy.price:.2f} ({latest_buy.timestamp})")
if latest_sell:
    print(f"最近卖点: {latest_sell.type.value} = {latest_sell.price:.2f} ({latest_sell.timestamp})")

# ============================================================
# 5. 操作信号
# ============================================================
print("\n" + "-" * 60)
print("【操作信号】")

signal_type = "hold"
signal_reasons = []

if latest_buy and latest_sell:
    if latest_buy.index > latest_sell.index:
        signal_type = "buy"
        signal_reasons.append(f"最近买点({latest_buy.type.value}={latest_buy.price:.2f})比卖点新")
    else:
        signal_type = "sell"
        signal_reasons.append(f"最近卖点({latest_sell.type.value}={latest_sell.price:.2f})比买点新")
elif latest_buy:
    signal_type = "buy"
    signal_reasons.append(f"出现{latest_buy.type.value}={latest_buy.price:.2f}")
elif latest_sell:
    signal_type = "sell"
    signal_reasons.append(f"出现{latest_sell.type.value}={latest_sell.price:.2f}")
else:
    signal_reasons.append("无明确买卖点信号")

if current_bi_dir == Direction.DOWN:
    if signal_type == "buy":
        signal_reasons.append("注意：当前笔仍在下跌中，买点可能尚未确认")
    else:
        signal_reasons.append("下跌笔中，等待企稳信号")
elif current_bi_dir == Direction.UP:
    signal_reasons.append("当前上涨笔中")

if in_zs and latest_zs:
    signal_reasons.append(f"在中枢[{latest_zs.low:.2f}, {latest_zs.high:.2f}]内震荡")
elif not in_zs and latest_zs:
    if current_price > latest_zs.high:
        signal_reasons.append("已脱离中枢上方，关注突破有效性")
    else:
        signal_reasons.append("已脱离中枢下方，关注是否企稳")

# 操作建议
print(f"\n信号: {signal_type.upper()}")
for r in signal_reasons:
    print(f"  - {r}")

print("\n" + "-" * 60)
print("【操作建议】")
if signal_type == "buy":
    stop_loss = latest_buy.price * 0.95
    print(f"  建议: 考虑买入")
    print(f"  入场价: {latest_buy.price:.2f}")
    print(f"  止损位: {stop_loss:.2f} ({latest_buy.type.value}低点下方5%)")
    if latest_zs:
        print(f"  目标位: {latest_zs.high:.2f} (中枢上沿)")
elif signal_type == "sell":
    print(f"  建议: 考虑卖出/减仓")
    if latest_sell:
        print(f"  卖出信号: {latest_sell.type.value} = {latest_sell.price:.2f}")
else:
    print(f"  建议: 观望等待")
    if latest_zs:
        print(f"  关注中枢区间: [{latest_zs.low:.2f}, {latest_zs.high:.2f}]")
        print(f"  向上突破 {latest_zs.high:.2f} 可考虑买入")
        print(f"  向下跌破 {latest_zs.low:.2f} 应继续观望")
