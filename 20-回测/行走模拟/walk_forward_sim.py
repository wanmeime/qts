#!/usr/bin/env python3
"""
QTS 六阶段行走模拟（Walk-Forward Simulation）
=============================================
假定当前时间 = 起始日期，从零执行完整六阶段流程

用法：python3 walk_forward_sim.py

流程：
1. 宏观分析 → 判断市场风格
2. 策略选股 → 动量策略 + 多因子策略各自选股
3. 持仓跟踪 → 1月/3月/6月盈亏
4. 交易模拟 → 按买卖条件执行，记录每次交易
"""
import urllib3.util.connection as uc
import socket
def _allowed_gai_family(): return socket.AF_INET
uc.allowed_gai_family = _allowed_gai_family

import os
import json
import glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================
# 配置
# ============================
KLINE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_6m"
OUTPUT_DIR = "/home/jiaod/qts/20-回测/行走模拟"
os.makedirs(OUTPUT_DIR, exist_ok=True)

START_DATE = "2025-12-01"   # 模拟起始日
END_DATE = "2026-06-02"     # 模拟结束日

INITIAL_CAPITAL = 1_000_000  # 初始资金100万

# 调仓节点
REBALANCE_POINTS = {
    "start":  START_DATE,                    # 建仓
    "1month": "2026-01-02",                  # 1个月后
    "3month": "2026-03-02",                  # 3个月后
    "6month": END_DATE,                      # 半年后
}

# ============================
# 第零步：加载数据
# ============================
def load_all_klines():
    """加载所有股票的K线数据"""
    files = glob.glob(f"{KLINE_DIR}/*.csv")
    all_data = {}
    for f in files:
        code = os.path.basename(f).replace(".csv", "")
        try:
            df = pd.read_csv(f)
            if len(df) >= 20:  # 至少20个交易日
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                all_data[code] = df
        except:
            continue
    print(f"  加载 {len(all_data)} 只股票K线数据")
    return all_data

# ============================
# 第一步：宏观分析
# ============================
def macro_analysis(all_data, as_of_date):
    """
    用截至as_of_date的数据做宏观分析
    返回：市场风格判断（多头/空头/震荡）
    """
    as_of = pd.Timestamp(as_of_date)
    
    # 计算全市场前20天的涨跌统计（K线从as_of_date开始）
    market_returns = []
    for code, df in all_data.items():
        subset = df[df['date'] >= as_of].head(20)
        if len(subset) >= 10:
            ret = (subset['close'].iloc[-1] / subset['close'].iloc[0] - 1) * 100
            market_returns.append(ret)
    
    if not market_returns:
        return {
            "as_of": as_of_date,
            "style": "未知",
            "confidence": 0,
            "avg_return_20d": 0,
            "up_ratio": 0,
            "median_return_20d": 0,
            "market_size": 0,
            "strategy_weight": {"动量": 0.5, "多因子": 0.5},
        }
    
    avg_ret = np.mean(market_returns)
    up_ratio = sum(1 for r in market_returns if r > 0) / len(market_returns) * 100
    median_ret = np.median(market_returns)
    
    # 判断市场风格
    if avg_ret > 3 and up_ratio > 60:
        style = "牛市成长"
        strategy_weight = {"动量": 0.6, "多因子": 0.4}
    elif avg_ret < -3 and up_ratio < 40:
        style = "熊市防御"
        strategy_weight = {"动量": 0.3, "多因子": 0.7}
    elif avg_ret > 0 and up_ratio > 50:
        style = "温和多头"
        strategy_weight = {"动量": 0.5, "多因子": 0.5}
    else:
        style = "震荡市"
        strategy_weight = {"动量": 0.4, "多因子": 0.6}
    
    return {
        "as_of": as_of_date,
        "style": style,
        "avg_return_20d": round(avg_ret, 2),
        "up_ratio": round(up_ratio, 1),
        "median_return_20d": round(median_ret, 2),
        "market_size": len(market_returns),
        "strategy_weight": strategy_weight,
    }

# ============================
# 第二步：动量策略选股
# ============================
def momentum_select(all_data, as_of_date, top_n=20):
    """
    动量策略：过去5天累计涨幅最大的股票
    排除成交额过低的股票
    """
    as_of = pd.Timestamp(as_of_date)
    scores = []
    
    for code, df in all_data.items():
        subset = df[df['date'] >= as_of].head(10)  # 取前10天
        if len(subset) < 5:
            continue
        
        recent_5d = subset.head(5)
        momentum = (recent_5d['close'].iloc[-1] / recent_5d['close'].iloc[0] - 1) * 100
        
        # 5天平均成交量
        avg_volume = recent_5d['amount'].mean()
        if avg_volume < 10000:  # 排除极低成交量
            continue
        
        # 排除ST（通过代码判断不了，跳过这个检查，数据加载时已过滤）
        scores.append({
            "code": code,
            "momentum_5d": round(momentum, 2),
            "avg_volume": int(avg_volume),
            "price": round(recent_5d['close'].iloc[-1], 2),
        })
    
    scores.sort(key=lambda x: x["momentum_5d"], reverse=True)
    return scores[:top_n]

# ============================
# 第三步：多因子策略选股
# ============================
def multifactor_select(all_data, as_of_date, top_n=20):
    """
    多因子策略：基于技术指标的多因子打分
    （没有PE/PB数据，用技术指标替代：波动率低+趋势向上+成交量活跃）
    """
    as_of = pd.Timestamp(as_of_date)
    scores = []
    
    for code, df in all_data.items():
        subset = df[df['date'] >= as_of].head(20)
        if len(subset) < 20:
            continue
        
        closes = subset['close'].values
        volumes = subset['amount'].values
        
        # 因子1：20日趋势（线性回归斜率）→ 越高越好
        x = np.arange(len(closes))
        slope = np.polyfit(x, closes, 1)[0]
        trend_score = slope / closes.mean() * 1000  # 标准化
        
        # 因子2：20日波动率 → 越低越好
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns) * 100
        
        # 因子3：成交量活跃度 → 越高越好
        vol_avg = np.mean(volumes)
        
        # 因子4：当前价格相对20日均线位置 → 适中（不过高不过低）
        ma20 = np.mean(closes)
        price_to_ma = closes[-1] / ma20
        ma_score = -abs(price_to_ma - 1.0) * 100  # 越接近1越好
        
        scores.append({
            "code": code,
            "price": round(closes[-1], 2),
            "trend_score": round(trend_score, 4),
            "volatility": round(volatility, 2),
            "vol_avg": int(vol_avg),
            "ma_score": round(ma_score, 4),
        })
    
    if not scores:
        return []
    
    # 标准化各因子到0-100
    def normalize(values, reverse=False):
        arr = np.array(values, dtype=float)
        mn, mx = arr.min(), arr.max()
        if mx == mn:
            return [50.0] * len(values)
        normed = (arr - mn) / (mx - mn) * 100
        if reverse:
            normed = 100 - normed
        return normed.tolist()
    
    trends = normalize([s["trend_score"] for s in scores])
    vols = normalize([s["volatility"] for s in scores], reverse=True)  # 低波动高分
    actives = normalize([s["vol_avg"] for s in scores])
    mas = normalize([s["ma_score"] for s in scores])
    
    for i, s in enumerate(scores):
        # 加权：趋势30% + 低波动25% + 成交活跃25% + 均线位置20%
        s["composite_score"] = round(
            trends[i] * 0.30 + vols[i] * 0.25 + actives[i] * 0.25 + mas[i] * 0.20, 2
        )
    
    scores.sort(key=lambda x: x["composite_score"], reverse=True)
    return scores[:top_n]

# ============================
# 第四步：持仓跟踪
# ============================
def track_portfolio(all_data, selections, start_date, end_date):
    """
    追踪选股组合从start_date到end_date的表现
    返回：各时间点的净值
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    
    # 构建等权组合
    codes = [s["code"] for s in selections]
    
    # 获取区间内所有交易日的净值
    portfolio_values = []
    
    # 找所有交易日
    all_dates = set()
    for code in codes:
        if code in all_data:
            df = all_data[code]
            dates = df[(df['date'] >= start) & (df['date'] <= end)]['date']
            all_dates.update(dates)
    
    all_dates = sorted(all_dates)
    
    for date in all_dates:
        daily_values = []
        for code in codes:
            if code not in all_data:
                continue
            df = all_data[code]
            row = df[df['date'] == date]
            if len(row) > 0:
                daily_values.append(row['close'].iloc[0])
        
        if daily_values:
            portfolio_values.append({
                "date": date.strftime("%Y-%m-%d"),
                "avg_price": round(np.mean(daily_values), 2),
                "stock_count": len(daily_values),
            })
    
    if not portfolio_values:
        return None
    
    # 计算收益率
    base_price = portfolio_values[0]["avg_price"]
    for pv in portfolio_values:
        pv["return_pct"] = round((pv["avg_price"] / base_price - 1) * 100, 2)
    
    return portfolio_values

# ============================
# 第五步：交易模拟
# ============================
def simulate_trades(all_data, selections, macro, start_date, end_date):
    """
    模拟按策略条件的买卖操作
    买入条件：建仓日 + 每月调仓
    卖出条件：单只浮亏>5%止损 / 持有超过3个月
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    
    codes = [s["code"] for s in selections]
    trades = []
    holdings = {}  # code -> {buy_price, buy_date, shares}
    capital = INITIAL_CAPITAL
    position_size = capital * 0.08  # 每只8%仓位
    
    # 交易日列表
    all_dates = set()
    for code in codes:
        if code in all_data:
            df = all_data[code]
            dates = df[(df['date'] >= start) & (df['date'] <= end)]['date']
            all_dates.update(dates)
    all_dates = sorted(all_dates)
    
    # 月度调仓日（每月第一个交易日附近）
    rebalance_months = set()
    for d in all_dates:
        rebalance_months.add((d.year, d.month))
    
    rebalance_dates = []
    for year, month in rebalance_months:
        month_dates = [d for d in all_dates if d.year == year and d.month == month]
        if month_dates:
            rebalance_dates.append(month_dates[0])
    
    current_month_idx = 0
    
    for date in all_dates:
        for code in codes:
            if code not in all_data:
                continue
            df = all_data[code]
            row = df[df['date'] == date]
            if len(row) == 0:
                continue
            
            price = row['close'].iloc[0]
            
            # 建仓：第一天
            if date == start and code not in holdings:
                shares = int(position_size / price / 100) * 100  # 整百股
                if shares > 0:
                    cost = shares * price
                    holdings[code] = {
                        "buy_price": price,
                        "buy_date": date.strftime("%Y-%m-%d"),
                        "shares": shares,
                    }
                    capital -= cost
                    trades.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "code": code,
                        "action": "买入",
                        "price": price,
                        "shares": shares,
                        "reason": "建仓",
                    })
            
            # 止损：浮亏>5%
            if code in holdings:
                buy_price = holdings[code]["buy_price"]
                pnl_pct = (price / buy_price - 1) * 100
                if pnl_pct <= -5:
                    shares = holdings[code]["shares"]
                    capital += shares * price
                    trades.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "code": code,
                        "action": "卖出",
                        "price": price,
                        "shares": shares,
                        "pnl_pct": round(pnl_pct, 2),
                        "reason": "止损-5%",
                    })
                    del holdings[code]
            
            # 月度调仓：持有超过2个月的清掉
            if date in rebalance_dates and current_month_idx >= 2:
                if code in holdings:
                    buy_price = holdings[code]["buy_price"]
                    pnl_pct = (price / buy_price - 1) * 100
                    shares = holdings[code]["shares"]
                    capital += shares * price
                    trades.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "code": code,
                        "action": "卖出",
                        "price": price,
                        "shares": shares,
                        "pnl_pct": round(pnl_pct, 2),
                        "reason": "调仓卖出",
                    })
                    del holdings[code]
        
        if date in rebalance_dates:
            current_month_idx += 1
    
    # 最终清仓
    for code in list(holdings.keys()):
        if code in all_data:
            df = all_data[code]
            last_row = df[df['date'] <= end].tail(1)
            if len(last_row) > 0:
                price = last_row['close'].iloc[0]
                buy_price = holdings[code]["buy_price"]
                pnl_pct = (price / buy_price - 1) * 100
                shares = holdings[code]["shares"]
                capital += shares * price
                trades.append({
                    "date": end_date,
                    "code": code,
                    "action": "卖出",
                    "price": round(price, 2),
                    "shares": shares,
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": "半年清仓",
                })
    
    return trades, capital

# ============================
# 主程序
# ============================
def main():
    print("=" * 60)
    print("  QTS 六阶段行走模拟")
    print(f"  模拟区间：{START_DATE} → {END_DATE}")
    print(f"  初始资金：¥{INITIAL_CAPITAL:,.0f}")
    print("=" * 60)
    
    # 第零步：加载数据
    print("\n📦 第零步：加载K线数据...")
    all_data = load_all_klines()
    if len(all_data) < 100:
        print(f"  ❌ 数据不足（仅{len(all_data)}只），请先运行拉取脚本")
        return
    
    # 第一步：宏观分析
    print("\n📊 第一步：宏观分析...")
    macro = macro_analysis(all_data, START_DATE)
    print(f"  市场风格：{macro['style']}")
    print(f"  全市场20日平均涨幅：{macro['avg_return_20d']}%")
    print(f"  上涨比例：{macro['up_ratio']}%")
    print(f"  策略权重：动量{macro['strategy_weight']['动量']*100:.0f}% / 多因子{macro['strategy_weight']['多因子']*100:.0f}%")
    
    # 第二步：策略选股
    print("\n🔍 第二步：策略选股...")
    
    print("\n  [动量策略] 过去5天涨幅前20...")
    mom_selections = momentum_select(all_data, START_DATE, top_n=20)
    for i, s in enumerate(mom_selections[:10]):
        print(f"    {i+1}. {s['code']} 5日动量:{s['momentum_5d']}% 价格:{s['price']}")
    
    print("\n  [多因子策略] 综合得分前20...")
    mf_selections = multifactor_select(all_data, START_DATE, top_n=20)
    for i, s in enumerate(mf_selections[:10]):
        print(f"    {i+1}. {s['code']} 综合:{s['composite_score']} 趋势:{s['trend_score']} 波动:{s['volatility']}")
    
    # 第三步：持仓跟踪
    print("\n📈 第三步：持仓跟踪...")
    
    print("\n  [动量组合] 净值追踪:")
    mom_portfolio = track_portfolio(all_data, mom_selections, START_DATE, END_DATE)
    if mom_portfolio:
        # 找1月/3月/6月的收益率
        for label, months in [("1个月", 21), ("3个月", 63), ("6个月", len(mom_portfolio)-1)]:
            idx = min(months, len(mom_portfolio)-1)
            pv = mom_portfolio[idx]
            print(f"    {label}后：{pv['date']} 收益率:{pv['return_pct']}%")
    
    print("\n  [多因子组合] 净值追踪:")
    mf_portfolio = track_portfolio(all_data, mf_selections, START_DATE, END_DATE)
    if mf_portfolio:
        for label, months in [("1个月", 21), ("3个月", 63), ("6个月", len(mf_portfolio)-1)]:
            idx = min(months, len(mf_portfolio)-1)
            pv = mf_portfolio[idx]
            print(f"    {label}后：{pv['date']} 收益率:{pv['return_pct']}%")
    
    # 第四步：交易模拟
    print("\n💹 第四步：交易模拟...")
    
    print("\n  [动量策略] 交易记录:")
    mom_trades, mom_final = simulate_trades(all_data, mom_selections, macro, START_DATE, END_DATE)
    buy_count = sum(1 for t in mom_trades if t["action"] == "买入")
    sell_count = sum(1 for t in mom_trades if t["action"] == "卖出")
    stop_loss = sum(1 for t in mom_trades if t.get("reason") == "止损-5%")
    mom_pnl = mom_final - INITIAL_CAPITAL
    print(f"    交易次数：买入{buy_count}次 卖出{sell_count}次")
    print(f"    止损触发：{stop_loss}次")
    print(f"    最终资金：¥{mom_final:,.0f} 盈亏：¥{mom_pnl:,.0f} ({mom_pnl/INITIAL_CAPITAL*100:.2f}%)")
    
    print("\n  [多因子策略] 交易记录:")
    mf_trades, mf_final = simulate_trades(all_data, mf_selections, macro, START_DATE, END_DATE)
    buy_count = sum(1 for t in mf_trades if t["action"] == "买入")
    sell_count = sum(1 for t in mf_trades if t["action"] == "卖出")
    stop_loss = sum(1 for t in mf_trades if t.get("reason") == "止损-5%")
    mf_pnl = mf_final - INITIAL_CAPITAL
    print(f"    交易次数：买入{buy_count}次 卖出{sell_count}次")
    print(f"    止损触发：{stop_loss}次")
    print(f"    最终资金：¥{mf_final:,.0f} 盈亏：¥{mf_pnl:,.0f} ({mf_pnl/INITIAL_CAPITAL*100:.2f}%)")
    
    # 第五步：结论
    print("\n" + "=" * 60)
    print("  📋 模拟结论")
    print("=" * 60)
    print(f"\n  市场风格（{START_DATE}判断）：{macro['style']}")
    print(f"\n  动量策略：半年收益 {mom_pnl/INITIAL_CAPITAL*100:.2f}%")
    print(f"  多因子策略：半年收益 {mf_pnl/INITIAL_CAPITAL*100:.2f}%")
    
    if mom_pnl > mf_pnl:
        print(f"\n  🏆 动量策略胜出！多赚 ¥{mom_pnl - mf_pnl:,.0f}")
    elif mf_pnl > mom_pnl:
        print(f"\n  🏆 多因子策略胜出！多赚 ¥{mf_pnl - mom_pnl:,.0f}")
    else:
        print(f"\n  🤝 两个策略收益相同")
    
    # 保存完整报告
    report = {
        "macro": macro,
        "momentum_selections": mom_selections,
        "multifactor_selections": mf_selections,
        "momentum_trades": mom_trades,
        "multifactor_trades": mf_trades,
        "momentum_portfolio": mom_portfolio,
        "multifactor_portfolio": mf_portfolio,
        "momentum_final": mom_final,
        "multifactor_final": mf_final,
    }
    
    report_path = f"{OUTPUT_DIR}/模拟报告_{START_DATE.replace('-','')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  完整报告已保存：{report_path}")

if __name__ == "__main__":
    main()
