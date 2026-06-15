#!/usr/bin/env python3
"""
拉取行业板块数据 + A股全市场快照
输出到 qts/00-研究/行业/
"""
import os
import sys
import time
import pandas as pd
import akshare as ak

BASE = "/home/jiaod/qts/00-研究/行业"
os.makedirs(BASE, exist_ok=True)

# === 1. 行业板块列表 ===
print("📊 拉取行业板块列表...")
try:
    industries = ak.stock_board_industry_name_em()
    industries.to_csv(f"{BASE}/行业板块列表.csv", index=False)
    print(f"  ✅ 共 {len(industries)} 个行业板块")
    print(f"  前10个: {industries['板块名称'].head(10).tolist()}")
except Exception as e:
    print(f"  ❌ 行业板块拉取失败: {e}")

time.sleep(1)

# === 2. A股全市场实时行情（用于行业轮动分析） ===
print("\n📊 拉取A股全市场行情...")
try:
    stocks = ak.stock_zh_a_spot_em()
    stocks.to_csv(f"{BASE}/../数据源/缓存/A股全市场行情.csv", index=False)
    print(f"  ✅ 共 {len(stocks)} 只股票")
    
    # 按行业统计
    if '所属行业' in stocks.columns:
        industry_stats = stocks.groupby('所属行业').agg({
            '涨跌幅': ['mean', 'count'],
            '成交额': 'sum'
        }).round(2)
        industry_stats.columns = ['平均涨跌幅', '股票数', '总成交额']
        industry_stats = industry_stats.sort_values('平均涨跌幅', ascending=False)
        industry_stats.to_csv(f"{BASE}/行业涨跌排名.csv")
        print(f"\n  📈 今日涨幅前5行业:")
        for name, row in industry_stats.head(5).iterrows():
            print(f"    {name}: +{row['平均涨跌幅']}% ({int(row['股票数'])}只)")
        print(f"\n  📉 今日跌幅前5行业:")
        for name, row in industry_stats.tail(5).iterrows():
            print(f"    {name}: {row['平均涨跌幅']}% ({int(row['股票数'])}只)")
except Exception as e:
    print(f"  ❌ A股行情拉取失败: {e}")

# === 3. 写行业轮动信号文件 ===
print("\n📊 生成行业轮动信号...")
try:
    signal = f"""# 行业轮动信号

> 更新时间: 2026-06-02

## 今日行业涨跌排名

### 涨幅前5
"""
    for name, row in industry_stats.head(5).iterrows():
        signal += f"- **{name}**: +{row['平均涨跌幅']}% ({int(row['股票数'])}只，成交{row['总成交额']/1e8:.0f}亿)\n"
    
    signal += "\n### 跌幅前5\n"
    for name, row in industry_stats.tail(5).iterrows():
        signal += f"- **{name}**: {row['平均涨跌幅']}% ({int(row['股票数'])}只，成交{row['总成交额']/1e8:.0f}亿)\n"
    
    signal += """
## 判断逻辑
- 连续3天排名前5的行业 → 热门行业（动量信号）
- 连续3天排名后5的行业 → 回避行业
- 成交额放大的行业 → 资金流入

## 当前结论
待连续数据积累后自动判断
"""
    with open(f"{BASE}/行业轮动信号.md", "w") as f:
        f.write(signal)
    print(f"  ✅ 行业轮动信号已生成")
except Exception as e:
    print(f"  ⚠️ 行业轮动信号生成失败: {e}")

print("\n✅ 行业数据拉取完成！")
