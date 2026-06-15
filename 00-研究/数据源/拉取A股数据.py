#!/usr/bin/env python3
"""
A股数据拉取 — 用新浪财经API（东财被限流）
"""
import subprocess
import json
import os
import time
import pandas as pd

BASE = "/home/jiaod/qts/00-研究"
CACHE = f"{BASE}/数据源/缓存"
os.makedirs(CACHE, exist_ok=True)
os.makedirs(f"{BASE}/行业", exist_ok=True)

def fetch_sina_page(page=1, num=80, sort='changepercent', asc=0):
    """新浪A股行情接口"""
    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num={num}&sort={sort}&asc={asc}&node=hs_a"
    result = subprocess.run(
        ['curl', '-s', '-4', '-H', 'User-Agent: Mozilla/5.0', url],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        return json.loads(result.stdout)
    return []

# === 1. 拉取全部A股（分页） ===
print("📊 拉取A股全市场行情（新浪）...")
all_stocks = []
for page in range(1, 80):  # 约5000只股票，每页80只
    items = fetch_sina_page(page=page, num=80)
    if not items:
        break
    all_stocks.extend(items)
    if page % 10 == 0:
        print(f"  已拉取 {len(all_stocks)} 只...")
    time.sleep(0.3)

if all_stocks:
    df = pd.DataFrame(all_stocks)
    # 重命名列
    col_map = {
        'symbol': '代码', 'code': '股票代码', 'name': '名称',
        'trade': '最新价', 'pricechange': '涨跌额', 'changepercent': '涨跌幅',
        'volume': '成交量', 'amount': '成交额',
        'settlement': '昨收', 'open': '今开', 'high': '最高', 'low': '最低',
        'per': '市盈率', 'pb': '市净率', 'mktcap': '总市值', 'nmc': '流通市值',
        'turnoverratio': '换手率'
    }
    df = df.rename(columns=col_map)
    
    # 数值类型转换
    for col in ['最新价','涨跌额','涨跌幅','成交量','成交额','昨收','今开','最高','最低','市盈率','市净率','总市值','流通市值','换手率']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 提取行业信息（从代码前缀判断交易所）
    df['交易所'] = df['代码'].apply(lambda x: '上交所' if 'sh' in str(x) else ('深交所' if 'sz' in str(x) else ('北交所' if 'bj' in str(x) else '未知')))
    
    df.to_csv(f"{CACHE}/A股全市场行情.csv", index=False)
    print(f"  ✅ 共 {len(df)} 只股票")
    
    # === 2. 涨跌统计 ===
    print(f"\n  📊 涨跌统计:")
    up = len(df[df['涨跌幅'] > 0])
    down = len(df[df['涨跌幅'] < 0])
    flat = len(df[df['涨跌幅'] == 0])
    print(f"    上涨: {up} 只 | 下跌: {down} 只 | 平盘: {flat} 只")
    
    print(f"\n  📈 涨幅前10:")
    top = df.nlargest(10, '涨跌幅')[['名称','最新价','涨跌幅','成交额','换手率']]
    for _, row in top.iterrows():
        print(f"    {row['名称']}: {row['最新价']}元 +{row['涨跌幅']:.2f}% 成交{row['成交额']/1e8:.1f}亿")
    
    print(f"\n  📉 跌幅前10:")
    bottom = df.nsmallest(10, '涨跌幅')[['名称','最新价','涨跌幅','成交额','换手率']]
    for _, row in bottom.iterrows():
        print(f"    {row['名称']}: {row['最新价']}元 {row['涨跌幅']:.2f}% 成交{row['成交额']/1e8:.1f}亿")
    
    # === 3. 写市场概况 ===
    overview = f"""# A股市场概况

> 数据来源: 新浪财经 · 更新时间: {time.strftime('%Y-%m-%d %H:%M')}

## 涨跌统计
- 上涨: {up} 只 | 下跌: {down} 只 | 平盘: {flat} 只
- 涨跌比: {up/down:.2f} (大于1为多头市场)

## 涨幅前10
"""
    for _, row in top.iterrows():
        overview += f"| {row['名称']} | {row['最新价']}元 | +{row['涨跌幅']:.2f}% | {row['成交额']/1e8:.1f}亿 |\n"
    
    overview += "\n## 跌幅前10\n"
    overview += "| 名称 | 最新价 | 涨跌幅 | 成交额 |\n|---|---|---|---|\n"
    for _, row in bottom.iterrows():
        overview += f"| {row['名称']} | {row['最新价']}元 | {row['涨跌幅']:.2f}% | {row['成交额']/1e8:.1f}亿 |\n"
    
    with open(f"{BASE}/市场概况.md", "w") as f:
        f.write(overview)
    print(f"\n  ✅ 市场概况已生成: {BASE}/市场概况.md")
else:
    print("  ❌ 未获取到数据")

print("\n✅ 数据拉取完成！")
