#!/usr/bin/env python3
"""
拉取自选股5年K线数据（腾讯源）
输出：qts/00-研究/数据源/缓存/kline_5y/
"""
import urllib3.util.connection as uc
import socket
def _allowed_gai_family(): return socket.AF_INET
uc.allowed_gai_family = _allowed_gai_family

import os
import time
import json
import pandas as pd
import akshare as ak

CACHE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_5y"
os.makedirs(CACHE_DIR, exist_ok=True)

# === 1. 加载自选股列表 ===
print("📊 读取自选股列表...")
with open("/home/jiaod/qts/00-研究/自选股/watchlist.json", encoding="utf-8") as f:
    watchlist = json.load(f)

stocks = []
for item in watchlist:
    code = item.get("code", "").strip()
    market = item.get("market", "")
    name = item.get("name", code)
    # 只保留A股，排除指数
    if not code or market == "美股" or code.startswith(("399", "880")):
        continue
    # 补齐前缀
    if code.startswith(("6", "9")):
        full_code = f"sh{code}"
    elif code.startswith(("0", "3")):
        full_code = f"sz{code}"
    else:
        full_code = code
    stocks.append((full_code, name))

print(f"自选股池：{len(stocks)} 只A股")

# === 2. 检查已完成 ===
done = set(f.replace(".csv", "") for f in os.listdir(CACHE_DIR) if f.endswith(".csv"))
remaining = [(c, n) for c, n in stocks if c not in done]
print(f"已完成：{len(done)} | 待拉取：{len(remaining)}")
print(f"预计时间：{len(remaining) * 0.6 / 60:.1f} 分钟")

# === 3. 拉取K线（腾讯源，5年数据）===
print("\n🚀 开始拉取K线数据...\n")
success = 0
fail = 0
start_time = time.time()

for i, (code, name) in enumerate(remaining):
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=code,
            start_date="20210620",
            end_date="20260620",
            adjust="qfq"
        )
        if df is not None and len(df) > 0:
            df.to_csv(f"{CACHE_DIR}/{code}.csv", index=False)
            success += 1
            print(f"  ✅ {code} ({name}) - {len(df)}条数据")
        else:
            fail += 1
            print(f"  ❌ {code} ({name}) - 无数据")
    except Exception as e:
        fail += 1
        print(f"  ❌ {code} ({name}) - 错误: {e}")
    
    if (i + 1) % 10 == 0 or i == len(remaining) - 1:
        elapsed = time.time() - start_time
        rate = (i + 1) / elapsed if elapsed > 0 else 0
        eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
        print(f"\n  [{i+1}/{len(remaining)}] 成功:{success} 失败:{fail} | 速率:{rate:.1f}/秒 | 剩余:{eta/60:.1f}分钟\n")
    
    time.sleep(0.3)

# === 4. 汇总 ===
elapsed = time.time() - start_time
total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in os.listdir(CACHE_DIR) if f.endswith(".csv"))
print(f"\n✅ 全部完成！")
print(f"  成功: {success} | 失败: {fail}")
print(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
print(f"  耗时: {elapsed / 60:.1f} 分钟")
