# -*- coding: utf-8 -*-
import sys
import os
import pandas as pd
import akshare as ak

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chanlun_agent import ChanlunAgent

def main():
    stock_code = "600186"
    print(f"开始分析 {stock_code}...")

    # 1. 获取日线数据
    print("获取日线数据...")
    try:
        daily_df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date="20251201", end_date="20260608")
        # 转换列名以匹配 Agent 要求
        daily_df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        print(f"日线数据获取成功，共 {len(daily_df)} 条记录")
    except Exception as e:
        print(f"日线数据获取失败: {e}")
        return

    # 2. 获取15分钟数据
    print("获取15分钟数据...")
    min15_df = None
    try:
        min15_df = ak.stock_zh_a_hist_min_em(symbol=stock_code, period="15", start_date="20260501 09:30:00", end_date="20260608 15:00:00")
        # 转换列名
        if not min15_df.empty:
            min15_df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
            print(f"15分钟数据获取成功，共 {len(min15_df)} 条记录")
        else:
            print("15分钟数据为空")
            min15_df = None
    except Exception as e:
        print(f"15分钟数据获取失败: {e}")

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
            min15_df = None # 不符合要求，不使用
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

if __name__ == "__main__":
    main()
