#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号转订单模块
读取动量信号和多因子信号，合并去重，生成交易订单

逻辑：
1. 读取动量轮动信号和多因子选股信号
2. 同一股票只保留综合得分更高的信号
3. 按资金管理规则生成订单（单只≤10%，总仓位≤80%）
4. 输出订单JSON文件
"""

import csv
import json
import os
import uuid
from datetime import datetime

# ==================== 配置 ====================
INITIAL_CAPITAL = 1000000  # 初始资金100万
MAX_SINGLE_POSITION = 0.10  # 单只最大仓位10%
MAX_TOTAL_POSITION = 0.80   # 总仓位上限80%

SIGNAL_DIR = "/home/jiaod/qts/30-信号"
ORDER_DIR = "/home/jiaod/qts/40-执行/订单"
SIGNAL_DATE = "20260602"


def load_momentum_signal(filepath):
    """加载动量轮动信号，返回 {股票代码: 信号字典}"""
    signals = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stock_code = row["股票代码"].strip()
            signals[stock_code] = {
                "股票代码": stock_code,
                "代码": row["代码"].strip(),
                "名称": row["名称"].strip(),
                "最新价": float(row["最新价"]),
                "涨跌幅": float(row["涨跌幅"]),
                "成交额": float(row["成交额"]),
                "换手率": float(row["换手率"]),
                "市盈率": float(row["市盈率"]) if row["市盈率"] else 0,
                "市净率": float(row["市净率"]) if row["市净率"] else 0,
                "总市值": float(row["总市值"]),
                "动量得分": float(row["动量得分"]),
                "信号来源": "动量轮动",
            }
    return signals


def load_multifactor_signal(filepath):
    """加载多因子选股信号，返回 {股票代码: 信号字典}"""
    signals = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stock_code = row["股票代码"].strip()
            signals[stock_code] = {
                "股票代码": stock_code,
                "代码": row["代码"].strip(),
                "名称": row["名称"].strip(),
                "最新价": float(row["最新价"]),
                "涨跌幅": float(row["涨跌幅"]),
                "成交额": float(row["成交额"]) if row.get("成交额") else 0,
                "换手率": float(row["换手率"]) if row.get("换手率") else 0,
                "市盈率": float(row["市盈率"]) if row["市盈率"] else 0,
                "市净率": float(row["市净率"]) if row["市净率"] else 0,
                "总市值": float(row["总市值"]) if row["总市值"] else 0,
                "综合得分": float(row["综合得分"]),
                "信号来源": "多因子选股",
            }
    return signals


def compute_signal_strength(stock, source):
    """
    计算信号强度（归一化到0-100）
    动量信号：以动量涨跌幅为基准（涨30%=100分）
    多因子信号：直接使用综合得分
    """
    if source == "动量轮动":
        # 涨跌幅30%封顶为100分
        return min(stock.get("涨跌幅", 0) / 30.0 * 100, 100)
    else:
        # 多因子综合得分本身在0-100范围
        return stock.get("综合得分", 50)


def merge_signals(momentum, multifactor):
    """
    合并两个信号源，同一只股票保留信号强度更高的
    返回合并后的信号列表，按信号强度降序排列
    """
    merged = {}

    # 先放入动量信号
    for code, stock in momentum.items():
        strength = compute_signal_strength(stock, "动量轮动")
        stock["信号强度"] = round(strength, 2)
        merged[code] = stock

    # 再放入多因子信号，覆盖同股票中信号强度更低的
    for code, stock in multifactor.items():
        strength = compute_signal_strength(stock, "多因子选股")
        stock["信号强度"] = round(strength, 2)
        if code in merged:
            # 同一股票：保留信号强度更高的
            if strength > merged[code]["信号强度"]:
                merged[code] = stock
        else:
            merged[code] = stock

    # 按信号强度降序排列
    sorted_list = sorted(merged.values(), key=lambda x: x["信号强度"], reverse=True)
    return sorted_list


def generate_orders(signal_list, signal_date):
    """
    根据信号列表生成交易订单
    资金管理：初始100万，单只≤10%=10万，总持仓≤80%=80万
    """
    orders = []
    total_committed = 0  # 已分配资金
    max_single = INITIAL_CAPITAL * MAX_SINGLE_POSITION   # 10万
    max_total = INITIAL_CAPITAL * MAX_TOTAL_POSITION      # 80万

    for stock in signal_list:
        # 检查总仓位是否已达上限
        if total_committed >= max_total:
            print(f"⚠️ 总仓位已达上限{MAX_TOTAL_POSITION*100:.0f}%，跳过后续信号")
            break

        price = stock["最新价"]
        if price <= 0:
            print(f"⚠️ {stock['名称']}价格异常({price})，跳过")
            continue

        # 计算建议仓位（信号强度越强，仓位越高）
        signal_strength = stock["信号强度"]
        # 信号强度70以上给满仓10%，50-70给8%，50以下给5%
        if signal_strength >= 70:
            position_pct = MAX_SINGLE_POSITION
        elif signal_strength >= 50:
            position_pct = 0.08
        else:
            position_pct = 0.05

        target_amount = INITIAL_CAPITAL * position_pct
        # 不超过剩余可分配资金
        target_amount = min(target_amount, max_total - total_committed)

        # 计算可买股数（取整到100股/手）
        shares = int(target_amount / price / 100) * 100
        if shares <= 0:
            print(f"⚠️ {stock['名称']}({stock['股票代码']})价格过高，无法买入1手，跳过")
            continue

        order_amount = shares * price
        actual_position_pct = order_amount / INITIAL_CAPITAL

        order = {
            "订单ID": f"ORD-{signal_date}-{str(uuid.uuid4())[:8]}",
            "股票代码": stock["股票代码"],
            "代码": stock["代码"],
            "名称": stock["名称"],
            "方向": "买入",
            "信号来源": stock["信号来源"],
            "信号强度": stock["信号强度"],
            "建议仓位%": round(actual_position_pct * 100, 2),
            "下单价格": price,
            "下单数量": shares,
            "下单金额": round(order_amount, 2),
            "下单时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "状态": "待执行",
        }

        orders.append(order)
        total_committed += order_amount
        print(f"✅ {stock['名称']}({stock['股票代码']}) 信号{signal_strength:.1f}分 "
              f"→ 买入{shares}股 @ {price} 仓位{actual_position_pct*100:.2f}%")

    print(f"\n📊 汇总：共{len(orders)}笔订单，已分配{total_committed:.2f}元，"
          f"占总资金{total_committed/INITIAL_CAPITAL*100:.2f}%")

    return orders


def main():
    """主函数"""
    print("=" * 60)
    print("🚀 信号转订单模块启动")
    print(f"📅 信号日期：{SIGNAL_DATE}")
    print(f"💰 初始资金：{INITIAL_CAPITAL:,.0f}元")
    print("=" * 60)

    # 1. 读取信号文件
    momentum_file = os.path.join(SIGNAL_DIR, f"动量轮动_买入信号_{SIGNAL_DATE}.csv")
    multifactor_file = os.path.join(SIGNAL_DIR, f"多因子选股_{SIGNAL_DATE}.csv")

    print(f"\n📂 读取动量信号：{momentum_file}")
    momentum = load_momentum_signal(momentum_file)
    print(f"   → 共{len(momentum)}只股票")

    print(f"📂 读取多因子信号：{multifactor_file}")
    multifactor = load_multifactor_signal(multifactor_file)
    print(f"   → 共{len(multifactor)}只股票")

    # 2. 合并去重
    print(f"\n🔗 合并去重（同股票保留更强信号）...")
    merged = merge_signals(momentum, multifactor)
    print(f"   → 合并后共{len(merged)}只股票")
    for i, s in enumerate(merged[:5], 1):
        print(f"   {i}. {s['名称']}({s['股票代码']}) 来源:{s['信号来源']} 强度:{s['信号强度']}")

    # 3. 生成订单
    print(f"\n📋 生成交易订单...")
    orders = generate_orders(merged, SIGNAL_DATE)

    # 4. 输出订单文件
    os.makedirs(ORDER_DIR, exist_ok=True)
    output_file = os.path.join(ORDER_DIR, f"{SIGNAL_DATE}-orders.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 订单已保存到：{output_file}")
    print(f"   共{len(orders)}笔订单")

    # 打印订单概览
    print("\n" + "=" * 60)
    print("📋 订单概览")
    print("-" * 60)
    print(f"{'序号':<4} {'名称':<10} {'代码':<8} {'方向':<4} {'数量':<8} "
          f"{'价格':<10} {'金额':<12} {'仓位%':<6} {'信号':<6}")
    print("-" * 60)
    for i, order in enumerate(orders, 1):
        print(f"{i:<4} {order['名称']:<10} {order['股票代码']:<8} {order['方向']:<4} "
              f"{order['下单数量']:<8} {order['下单价格']:<10} "
              f"{order['下单金额']:<12,.2f} {order['建议仓位%']:<6} "
              f"{order['信号强度']:<6}")
    print("=" * 60)

    return orders


if __name__ == "__main__":
    main()
