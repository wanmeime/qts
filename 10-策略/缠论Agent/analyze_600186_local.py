# -*- coding: utf-8 -*-
import sys
import os
import pandas as pd

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chanlun_agent import ChanlunAgent

def main():
    stock_code = "600186"
    print(f"开始分析 {stock_code} (使用本地缓存数据)...")

    # 1. 获取日线数据
    cache_path = "/home/jiaod/qts/00-研究/数据源/缓存/kline_6m/sh600186.csv"
    if not os.path.exists(cache_path):
        print(f"日线数据缓存文件不存在: {cache_path}")
        return

    daily_df = pd.read_csv(cache_path)
    # 检查列名，根据读到的数据，列名是 date, open, close, high, low, amount
    # Agent 需要 open, high, low, close, volume
    # 读到的数据列名是: date, open, close, high, low, amount
    required_cols = ['open', 'high', 'low', 'close']
    if not all(c in daily_df.columns for c in required_cols):
        print(f"日线数据缺少必要的列: {daily_df.columns}")
        return

    # 重命名 amount 为 volume 以匹配 Agent 要求
    if 'amount' in daily_df.columns and 'volume' not in daily_df.columns:
        daily_df.rename(columns={'amount': 'volume'}, inplace=True)

    # 转换为 float 类型
    for col in required_cols + ['volume']:
        if col in daily_df.columns:
            daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce')

    print(f"日线数据加载成功，共 {len(daily_df)} 条记录")

    # 2. 调用分析 (不使用15分钟数据，因为没有本地缓存)
    agent = ChanlunAgent()
    print("开始调用缠论 Agent 分析...")

    result = agent.analyze(stock_code, daily_df)

    # 3. 输出分析报告
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

if __name__ == "__main__":
    main()
