#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓管理模块
读取订单文件，模拟成交，管理持仓

逻辑：
1. 读取订单JSON
2. 以信号中的最新价模拟成交（扣万3手续费）
3. 输出当前持仓、持仓汇总
4. 保存历史持仓快照
"""

import json
import os
from datetime import datetime

# ==================== 配置 ====================
INITIAL_CAPITAL = 1000000  # 初始资金100万
COMMISSION_RATE = 0.0003   # 手续费万3
SIGNAL_DATE = "20260602"

ORDER_DIR = "/home/jiaod/qts/40-执行/订单"
POSITION_DIR = "/home/jiaod/qts/40-执行/持仓"
HISTORY_DIR = os.path.join(POSITION_DIR, "历史持仓")


def load_orders(filepath):
    """加载订单文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def simulate_execution(orders):
    """
    模拟订单成交
    以订单中的下单价格成交，扣万3手续费
    返回成交后的持仓列表和剩余资金
    """
    positions = []
    total_cost = 0  # 总成交金额（含手续费）

    for order in orders:
        if order["状态"] == "待执行":
            price = order["下单价格"]
            shares = order["下单数量"]
            amount = price * shares
            commission = round(amount * COMMISSION_RATE, 2)  # 手续费
            total_amount = amount + commission  # 实际扣款

            position = {
                "股票代码": order["股票代码"],
                "代码": order["代码"],
                "名称": order["名称"],
                "持股数量": shares,
                "成本价": round(price + commission / shares, 4),  # 含手续费的持仓成本
                "买入价": price,
                "当前价": price,  # 模拟以买入价为当前价
                "市值": amount,
                "手续费": commission,
                "盈亏": 0,  # 刚买入盈亏为0
                "盈亏率": 0,
                "信号来源": order["信号来源"],
                "信号强度": order["信号强度"],
            }
            positions.append(position)
            total_cost += total_amount

            print(f"✅ 成交：{order['名称']} {shares}股 @ {price} "
                  f"金额{amount:,.2f} 手续费{commission:.2f}")

    available_cash = INITIAL_CAPITAL - total_cost
    return positions, available_cash


def compute_position_summary(positions, available_cash):
    """计算持仓汇总"""
    total_market_value = sum(p["市值"] for p in positions)
    total_pnl = sum(p["盈亏"] for p in positions)
    total_cost = sum(p["成本价"] * p["持股数量"] for p in positions)
    position_ratio = total_market_value / INITIAL_CAPITAL * 100

    summary = {
        "总资产": round(INITIAL_CAPITAL + total_pnl, 2),
        "总市值": round(total_market_value, 2),
        "总盈亏": round(total_pnl, 2),
        "总手续费": round(sum(p["手续费"] for p in positions), 2),
        "可用资金": round(available_cash, 2),
        "持仓比例%": round(position_ratio, 2),
        "持仓股数": len(positions),
        "初始资金": INITIAL_CAPITAL,
    }
    return summary


def save_current_positions(positions, summary, available_cash):
    """保存当前持仓到JSON"""
    output = {
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "信号日期": SIGNAL_DATE,
        "持仓汇总": summary,
        "持仓明细": positions,
    }
    filepath = os.path.join(POSITION_DIR, "当前持仓.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 当前持仓已保存：{filepath}")
    return filepath


def save_history_snapshot(positions, summary):
    """保存历史持仓快照"""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    snapshot = {
        "快照时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "信号日期": SIGNAL_DATE,
        "持仓汇总": summary,
        "持仓明细": positions,
    }
    filepath = os.path.join(HISTORY_DIR, f"{SIGNAL_DATE}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"✅ 历史快照已保存：{filepath}")
    return filepath


def main():
    """主函数"""
    print("=" * 60)
    print("🏦 持仓管理模块启动")
    print(f"📅 信号日期：{SIGNAL_DATE}")
    print(f"💰 初始资金：{INITIAL_CAPITAL:,.0f}元")
    print(f"📊 手续费率：万{COMMISSION_RATE*10000:.0f}")
    print("=" * 60)

    # 1. 读取订单
    order_file = os.path.join(ORDER_DIR, f"{SIGNAL_DATE}-orders.json")
    print(f"\n📂 读取订单文件：{order_file}")
    orders = load_orders(order_file)
    print(f"   → 共{len(orders)}笔订单")

    # 2. 模拟成交
    print(f"\n🔄 模拟成交中...")
    positions, available_cash = simulate_execution(orders)

    # 3. 计算汇总
    summary = compute_position_summary(positions, available_cash)

    # 4. 保存结果
    save_current_positions(positions, summary, available_cash)
    save_history_snapshot(positions, summary)

    # 5. 打印持仓概览
    print("\n" + "=" * 60)
    print("📊 持仓汇总")
    print("-" * 60)
    print(f"  初始资金：{summary['初始资金']:>14,.2f}元")
    print(f"  总 市 值：{summary['总市值']:>14,.2f}元")
    print(f"  可用资金：{summary['可用资金']:>14,.2f}元")
    print(f"  总 手 续 费：{summary['总手续费']:>12,.2f}元")
    print(f"  持仓比例：{summary['持仓比例%']:>13.2f}%")
    print(f"  持仓股数：{summary['持仓股数']:>14}只")
    print("-" * 60)

    print(f"\n📋 持仓明细")
    print("-" * 60)
    print(f"{'序号':<4} {'名称':<10} {'代码':<8} {'数量':<8} {'成本价':<10} "
          f"{'当前价':<10} {'市值':<12} {'盈亏':<10} {'盈亏率%':<8}")
    print("-" * 60)
    for i, pos in enumerate(positions, 1):
        print(f"{i:<4} {pos['名称']:<10} {pos['股票代码']:<8} {pos['持股数量']:<8} "
              f"{pos['成本价']:<10} {pos['当前价']:<10} "
              f"{pos['市值']:<12,.2f} {pos['盈亏']:<10} {pos['盈亏率']:<8}")
    print("=" * 60)

    return positions, summary


if __name__ == "__main__":
    main()
