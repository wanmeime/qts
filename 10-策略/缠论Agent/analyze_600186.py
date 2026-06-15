# -*- coding: utf-8 -*-
import sys
import os
import pandas as pd
import akshare as ak
import requests
from datetime import datetime, timedelta

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chanlun_agent import ChanlunAgent

def fetch_data_with_retry(symbol, period, start_date, end_date, retries=3):
    """带重试的数据获取"""
    for i in range(retries):
        try:
            if period == "daily":
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date)
                df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
            else:
                df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, start_date=start_date, end_date=end_date)
                if not df.empty:
                    df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
            return df
        except Exception as e:
            print(f"获取数据失败 (第{i+1}次): {e}")
            if i < retries - 1:
                import time
                time.sleep(2)
    return None

def main():
    stock_code = "600186"
    print(f"开始分析 {stock_code}...")

    # 计算日期范围
    end_date = datetime.now().strftime('%Y%m%d')
    start_date_daily = (datetime.now() - timedelta(days=180)).strftime('%Y%m%d')  # 6个月
    start_date_min15 = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')  # 1个月

    # 1. 获取日线数据
    print(f"获取日线数据 ({start_date_daily} 至 {end_date})...")
    daily_df = fetch_data_with_retry(stock_code, "daily", start_date_daily, end_date)

    if daily_df is None or daily_df.empty:
        print("日线数据获取失败，无法进行分析")
        return

    print(f"日线数据获取成功，共 {len(daily_df)} 条记录")

    # 2. 获取15分钟数据
    print(f"获取15分钟数据 ({start_date_min15} 至 {end_date})...")
    min15_df = fetch_data_with_retry(stock_code, "15", f"{start_date_min15} 09:30:00", f"{end_date} 15:00:00")

    if min15_df is not None and not min15_df.empty:
        print(f"15分钟数据获取成功，共 {len(min15_df)} 条记录")
    else:
        print("15分钟数据获取失败，将仅使用日线数据分析")
        min15_df = None

    # 3. 调用分析
    agent = ChanlunAgent()
    print("开始调用缠论 Agent 分析...")

    # 确保数据包含必要的列且类型正确
    required_cols = ['open', 'high', 'low', 'close']
    if not all(c in daily_df.columns for c in required_cols):
        print("日线数据缺少必要的列")
        return

    # 转换为 float 类型
    for col in required_cols:
        daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce')

    if min15_df is not None:
        if not all(c in min15_df.columns for c in required_cols):
            min15_df = None
        else:
            for col in required_cols:
                min15_df[col] = pd.to_numeric(min15_df[col], errors='coerce')

    result = agent.analyze(stock_code, daily_df, min15_df)

    # 4. 输出分析报告
    print("\n" + "="*60)
    print("莲花控股 (600186) 缠论分析报告")
    print("="*60)
    print(result['report'])

    # 打印信号详情
    print("\n" + "-"*60)
    print("交易信号详情")
    print("-"*60)
    signal = result['signal']
    print(f"信号类型: {signal['type'].upper()}")
    print(f"信号强度: {signal['strength']:.2f}")
    if signal['reasons']:
        print("\n信号原因:")
        for reason in signal['reasons']:
            print(f"  - {reason}")
    if signal['key_prices']:
        print("\n关键价位:")
        for name, price in signal['key_prices'].items():
            print(f"  {name}: {price:.2f}")
    if signal['stop_loss']:
        print(f"\n止损位: {signal['stop_loss']:.2f}")

    # 打印多级别分析结果
    if result['multi_level']:
        print("\n" + "-"*60)
        print("多级别联立分析")
        print("-"*60)
        print(result['multi_level'].summary)

if __name__ == "__main__":
    main()
