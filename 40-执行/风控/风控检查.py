#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风控检查模块
检查持仓是否符合风控规则，输出风控报告

检查项目：
1. 单只仓位是否超过10%上限
2. 总仓位是否超过80%
3. 单只浮亏是否超过5%触发止损
4. 组合浮亏是否超过10%触发全面止损
"""

import json
import os
from datetime import datetime

# ==================== 风控参数 ====================
INITIAL_CAPITAL = 1000000   # 初始资金100万
MAX_SINGLE_POSITION = 0.10  # 单只仓位上限10%
MAX_TOTAL_POSITION = 0.80   # 总仓位上限80%
SINGLE_STOP_LOSS = -0.05    # 单只止损线-5%
PORTFOLIO_STOP_LOSS = -0.10 # 组合止损线-10%

POSITION_DIR = "/home/jiaod/qts/40-执行/持仓"
REPORT_DIR = "/home/jiaod/qts/40-执行/风控"
SIGNAL_DATE = "20260602"


def load_current_positions(filepath):
    """加载当前持仓"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def check_single_position_limit(positions, total_asset):
    """
    检查单只仓位是否超过10%上限
    返回：[{股票代码, 名称, 市值, 仓位比例, 是否超限}]
    """
    results = []
    for pos in positions:
        ratio = pos["市值"] / total_asset if total_asset > 0 else 0
        over_limit = ratio > MAX_SINGLE_POSITION
        results.append({
            "股票代码": pos["股票代码"],
            "名称": pos["名称"],
            "市值": pos["市值"],
            "仓位比例": round(ratio * 100, 2),
            "上限%": MAX_SINGLE_POSITION * 100,
            "是否超限": "⚠️ 超限" if over_limit else "✅ 正常",
        })
    return results


def check_total_position(positions, total_asset):
    """
    检查总仓位是否超过80%
    返回：{总市值, 总仓位比例, 是否超限}
    """
    total_market_value = sum(p["市值"] for p in positions)
    ratio = total_market_value / total_asset if total_asset > 0 else 0
    return {
        "总市值": total_market_value,
        "总仓位比例": round(ratio * 100, 2),
        "上限%": MAX_TOTAL_POSITION * 100,
        "是否超限": "⚠️ 超限" if ratio > MAX_TOTAL_POSITION else "✅ 正常",
    }


def check_single_stop_loss(positions):
    """
    检查单只浮亏是否超过5%触发止损
    返回：[{股票代码, 名称, 成本价, 当前价, 浮亏率, 是否触发止损}]
    """
    results = []
    for pos in positions:
        cost = pos["成本价"]
        current = pos["当前价"]
        pnl_rate = (current - cost) / cost if cost > 0 else 0
        trigger_stop = pnl_rate <= SINGLE_STOP_LOSS
        results.append({
            "股票代码": pos["股票代码"],
            "名称": pos["名称"],
            "成本价": cost,
            "当前价": current,
            "浮亏率": round(pnl_rate * 100, 2),
            "止损线%": SINGLE_STOP_LOSS * 100,
            "是否触发止损": "🔴 触发" if trigger_stop else "🟢 正常",
        })
    return results


def check_portfolio_stop_loss(positions, total_cost):
    """
    检查组合总浮亏是否超过10%
    返回：{总成本, 总市值, 总浮亏率, 是否触发}
    """
    total_market_value = sum(p["市值"] for p in positions)
    total_pnl_rate = (total_market_value - total_cost) / total_cost if total_cost > 0 else 0
    return {
        "总成本": round(total_cost, 2),
        "总市值": total_market_value,
        "总浮亏率": round(total_pnl_rate * 100, 2),
        "止损线%": PORTFOLIO_STOP_LOSS * 100,
        "是否触发": "🔴 触发" if total_pnl_rate <= PORTFOLIO_STOP_LOSS else "🟢 正常",
    }


def generate_report(position_check, total_check, stop_loss_check, portfolio_check, positions, summary):
    """生成风控检查报告Markdown"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""# QTS 风控检查报告

> 检查时间：{now}
> 信号日期：{SIGNAL_DATE}

---

## 一、持仓概览

| 项目 | 数值 |
|------|------|
| 初始资金 | {INITIAL_CAPITAL:,.2f} 元 |
| 总市值 | {summary.get('总市值', 0):,.2f} 元 |
| 可用资金 | {summary.get('可用资金', 0):,.2f} 元 |
| 持仓股数 | {summary.get('持仓股数', 0)} 只 |
| 总仓位 | {total_check['总仓位比例']:.2f}% |

---

## 二、单只仓位检查（上限{MAX_SINGLE_POSITION*100:.0f}%）

| 股票代码 | 名称 | 市值(元) | 仓位比例 | 上限 | 状态 |
|---------|------|---------|---------|------|------|
"""

    for item in position_check:
        report += (f"| {item['股票代码']} | {item['名称']} | "
                   f"{item['市值']:,.2f} | {item['仓位比例']:.2f}% | "
                   f"{item['上限%']:.0f}% | {item['是否超限']} |\n")

    # 统计超限数量
    over_count = sum(1 for item in position_check if "超限" in item["是否超限"])
    if over_count > 0:
        report += f"\n> ⚠️ **{over_count}只股票仓位超限，请注意减仓！**\n"
    else:
        report += f"\n> ✅ 所有股票仓位均在限额内\n"

    report += f"""
---

## 三、总仓位检查（上限{MAX_TOTAL_POSITION*100:.0f}%）

| 项目 | 数值 |
|------|------|
| 持仓总市值 | {total_check['总市值']:,.2f} 元 |
| 总仓位比例 | {total_check['总仓位比例']:.2f}% |
| 上限 | {total_check['上限%']:.0f}% |
| 状态 | {total_check['是否超限']} |

"""

    if "超限" in total_check["是否超限"]:
        report += "> ⚠️ **总仓位超限，建议降低持仓至80%以下！**\n"
    else:
        report += "> ✅ 总仓位在限额内\n"

    report += f"""
---

## 四、单只止损检查（止损线{SINGLE_STOP_LOSS*100:.0f}%）

| 股票代码 | 名称 | 成本价 | 当前价 | 浮亏率 | 止损线 | 状态 |
|---------|------|--------|--------|--------|--------|------|
"""

    for item in stop_loss_check:
        report += (f"| {item['股票代码']} | {item['名称']} | "
                   f"{item['成本价']:.4f} | {item['当前价']:.2f} | "
                   f"{item['浮亏率']:.2f}% | {item['止损线%']:.0f}% | "
                   f"{item['是否触发止损']} |\n")

    trigger_count = sum(1 for item in stop_loss_check if "触发" in item["是否触发止损"])
    if trigger_count > 0:
        report += f"\n> 🔴 **{trigger_count}只股票触发止损信号，建议立即卖出！**\n"
    else:
        report += f"\n> 🟢 所有股票浮亏在止损线内\n"

    report += f"""
---

## 五、组合止损检查（止损线{PORTFOLIO_STOP_LOSS*100:.0f}%）

| 项目 | 数值 |
|------|------|
| 总成本 | {portfolio_check['总成本']:,.2f} 元 |
| 总市值 | {portfolio_check['总市值']:,.2f} 元 |
| 总浮亏率 | {portfolio_check['总浮亏率']:.2f}% |
| 止损线 | {portfolio_check['止损线%']:.0f}% |
| 状态 | {portfolio_check['是否触发']} |

"""

    if "触发" in portfolio_check["是否触发"]:
        report += "> 🔴 **组合触发止损，建议全面清仓！**\n"
    else:
        report += "> 🟢 组合浮亏在止损线内\n"

    # 总结
    total_alerts = (over_count + trigger_count +
                    (1 if "超限" in total_check["是否超限"] else 0) +
                    (1 if "触发" in portfolio_check["是否触发"] else 0))

    report += f"""
---

## 六、风控总结

| 检查项 | 状态 |
|--------|------|
| 单只仓位上限 | {'⚠️ ' + str(over_count) + '只超限' if over_count > 0 else '✅ 全部正常'} |
| 总仓位上限 | {total_check['是否超限']} |
| 单只止损 | {'⚠️ ' + str(trigger_count) + '只触发' if trigger_count > 0 else '🟢 全部正常'} |
| 组合止损 | {portfolio_check['是否触发']} |
| **预警总数** | **{total_alerts}项** |

"""

    if total_alerts == 0:
        report += "> ✅ **风控检查全部通过，无需操作。**\n"
    else:
        report += f"> ⚠️ **共{total_alerts}项风控预警，请及时处理！**\n"

    return report


def main():
    """主函数"""
    print("=" * 60)
    print("🛡️ 风控检查模块启动")
    print(f"📅 信号日期：{SIGNAL_DATE}")
    print(f"📋 风控参数：单只止损{SINGLE_STOP_LOSS*100:.0f}% | "
          f"组合止损{PORTFOLIO_STOP_LOSS*100:.0f}% | "
          f"单只仓位{MAX_SINGLE_POSITION*100:.0f}% | "
          f"总仓位{MAX_TOTAL_POSITION*100:.0f}%")
    print("=" * 60)

    # 1. 读取持仓
    position_file = os.path.join(POSITION_DIR, "当前持仓.json")
    print(f"\n📂 读取持仓文件：{position_file}")
    data = load_current_positions(position_file)
    positions = data["持仓明细"]
    summary = data["持仓汇总"]
    print(f"   → 共{len(positions)}只持仓，总市值{summary['总市值']:,.2f}元")

    total_asset = summary["初始资金"] + summary["总盈亏"]
    total_cost = sum(p["成本价"] * p["持股数量"] for p in positions)

    # 2. 执行风控检查
    print(f"\n🔍 执行风控检查...")

    # R03: 单只仓位检查
    position_check = check_single_position_limit(positions, total_asset)
    print(f"   R03 单只仓位检查：完成")

    # R04: 总仓位检查
    total_check = check_total_position(positions, total_asset)
    print(f"   R04 总仓位检查：{total_check['是否超限']}")

    # R01: 单只止损检查
    stop_loss_check = check_single_stop_loss(positions)
    print(f"   R01 单只止损检查：完成")

    # R02: 组合止损检查
    portfolio_check = check_portfolio_stop_loss(positions, total_cost)
    print(f"   R02 组合止损检查：{portfolio_check['是否触发']}")

    # 3. 生成报告
    report = generate_report(
        position_check, total_check, stop_loss_check,
        portfolio_check, positions, summary
    )

    # 4. 保存报告
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_file = os.path.join(REPORT_DIR, "风控检查报告.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 风控报告已保存：{report_file}")

    # 5. 打印摘要
    over_count = sum(1 for item in position_check if "超限" in item["是否超限"])
    trigger_count = sum(1 for item in stop_loss_check if "触发" in item["是否触发止损"])
    print(f"\n📊 风控摘要：")
    print(f"   单只仓位超限：{over_count}只")
    print(f"   总仓位状态：{total_check['是否超限']}")
    print(f"   止损触发：{trigger_count}只")
    print(f"   组合止损：{portfolio_check['是否触发']}")

    return report_file


if __name__ == "__main__":
    main()
