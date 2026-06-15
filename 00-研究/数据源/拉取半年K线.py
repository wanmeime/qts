#!/usr/bin/env python3
"""
拉取全A股半年K线数据（腾讯源）+ 行业分类（同花顺）
输出：qts/00-研究/数据源/缓存/kline_6m/
"""
import urllib3.util.connection as uc
import socket
def _allowed_gai_family(): return socket.AF_INET
uc.allowed_gai_family = _allowed_gai_family

import os
import time
import csv
import pandas as pd
import akshare as ak

CACHE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_6m"
os.makedirs(CACHE_DIR, exist_ok=True)

# === 1. 拉取全市场股票列表 ===
print("📊 读取A股列表...")
stocks = []
with open("/home/jiaod/qts/00-研究/数据源/缓存/A股全市场行情.csv", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row.get("代码", "")
        name = row.get("名称", "")
        if "ST" in name or "退" in name:
            continue
        if code.startswith("sh") or code.startswith("sz") or code.startswith("bj"):
            stocks.append((code, name))

print(f"股票池：{len(stocks)} 只（排除ST/退市）")

# === 2. 检查已完成 ===
done = set(f.replace(".csv", "") for f in os.listdir(CACHE_DIR) if f.endswith(".csv"))
remaining = [(c, n) for c, n in stocks if c not in done]
print(f"已完成：{len(done)} | 待拉取：{len(remaining)}")
print(f"预计时间：{len(remaining) * 0.6 / 60:.0f} 分钟")

# === 3. 拉取K线（腾讯源）===
print("\n🚀 开始拉取K线数据...\n")
success = 0
fail = 0
start_time = time.time()

for i, (code, name) in enumerate(remaining):
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=code,
            start_date="20251201",
            end_date="20260602",
            adjust="qfq"
        )
        if df is not None and len(df) > 0:
            df.to_csv(f"{CACHE_DIR}/{code}.csv", index=False)
            success += 1
        else:
            fail += 1
    except Exception as e:
        fail += 1
    
    if (i + 1) % 50 == 0 or i == len(remaining) - 1:
        elapsed = time.time() - start_time
        rate = (i + 1) / elapsed
        eta = (len(remaining) - i - 1) / rate
        print(f"  [{i+1}/{len(remaining)}] 成功:{success} 失败:{fail} | 速率:{rate:.1f}/秒 | 剩余:{eta/60:.0f}分钟")
    
    time.sleep(0.3)

# === 4. 拉取行业分类 ===
print("\n📊 拉取同花顺行业分类...")
try:
    industries = ak.stock_board_industry_name_ths()
    industries.to_csv(f"/home/jiaod/qts/00-研究/数据源/缓存/ths_行业板块.csv", index=False)
    print(f"  ✅ {len(industries)} 个行业板块")
except Exception as e:
    print(f"  ❌ 失败: {e}")

# === 5. 汇总 ===
elapsed = time.time() - start_time
total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in os.listdir(CACHE_DIR) if f.endswith(".csv"))
print(f"\n✅ 全部完成！")
print(f"  成功: {success} | 失败: {fail}")
print(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
print(f"  耗时: {elapsed / 60:.1f} 分钟")
