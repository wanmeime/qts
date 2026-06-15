#!/usr/bin/env python3
"""
拉取宏观数据：CPI、PMI、Shibor、LPR
输出到 qts/00-研究/宏观/ 各子目录
"""
import os
import sys
import time
import pandas as pd
import akshare as ak

BASE = "/home/jiaod/qts/00-研究/宏观"
os.makedirs(f"{BASE}/CPI", exist_ok=True)
os.makedirs(f"{BASE}/PMI", exist_ok=True)
os.makedirs(f"{BASE}/流动性", exist_ok=True)

# === 1. CPI ===
print("📊 拉取CPI数据...")
try:
    cpi = ak.macro_china_cpi()
    cpi.to_csv(f"{BASE}/CPI/CPI_月度.csv", index=False)
    latest = cpi.iloc[-1] if len(cpi) > 0 else None
    print(f"  ✅ CPI: {len(cpi)}条记录，最新: {latest.to_dict() if latest is not None else 'N/A'}")
except Exception as e:
    print(f"  ❌ CPI拉取失败: {e}")

time.sleep(1)

# === 2. PMI ===
print("📊 拉取PMI数据...")
try:
    pmi = ak.macro_china_pmi()
    pmi.to_csv(f"{BASE}/PMI/PMI_月度.csv", index=False)
    latest = pmi.iloc[-1] if len(pmi) > 0 else None
    print(f"  ✅ PMI: {len(pmi)}条记录，最新: {latest.to_dict() if latest is not None else 'N/A'}")
except Exception as e:
    print(f"  ❌ PMI拉取失败: {e}")

time.sleep(1)

# === 3. Shibor ===
print("📊 拉取Shibor利率...")
try:
    shibor = ak.macro_china_shibor_all()
    shibor.to_csv(f"{BASE}/流动性/Shibor.csv", index=False)
    latest = shibor.iloc[-1] if len(shibor) > 0 else None
    print(f"  ✅ Shibor: {len(shibor)}条记录，最新: {latest.to_dict() if latest is not None else 'N/A'}")
except Exception as e:
    print(f"  ❌ Shibor拉取失败: {e}")
    # 尝试备选接口
    try:
        shibor = ak.rate_interbank(market="中国", symbol="Shibor人民币", indicator="今日")
        print(f"  ✅ Shibor(备选): {len(shibor)}条记录")
    except Exception as e2:
        print(f"  ❌ Shibor备选也失败: {e2}")

time.sleep(1)

# === 4. GDP ===
print("📊 拉取GDP数据...")
try:
    gdp = ak.macro_china_gdp()
    gdp.to_csv(f"{BASE}/GDP_季度.csv", index=False)
    latest = gdp.iloc[-1] if len(gdp) > 0 else None
    print(f"  ✅ GDP: {len(gdp)}条记录，最新: {latest.to_dict() if latest is not None else 'N/A'}")
except Exception as e:
    print(f"  ❌ GDP拉取失败: {e}")

print("\n✅ 宏观数据拉取完成！")
print(f"数据目录: {BASE}")
