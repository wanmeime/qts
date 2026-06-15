# -*- coding: utf-8 -*-
"""
缠论分析 Agent 使用示例

演示如何使用 Agent 进行股票分析
"""

import pandas as pd
import numpy as np
from datetime import datetime

# 添加当前目录到路径
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chanlun_agent import ChanlunAgent

def create_sample_data():
    """创建示例K线数据"""
    # 生成50天的模拟数据
    dates = pd.date_range('2023-01-01', periods=50, freq='D')

    # 模拟一个先下跌后上涨的走势
    prices = []
    # 下跌段 (0-15)
    for i in range(16):
        prices.append(100 - i * 2)
    # 上涨段 (16-30)
    for i in range(15):
        prices.append(68 + i * 3)
    # 震荡段 (31-40)
    for i in range(10):
        prices.append(113 + np.sin(i) * 5)
    # 最后上涨 (41-49)
    for i in range(9):
        prices.append(118 + i * 2)

    df = pd.DataFrame({
        'open': prices,
        'high': [p + 2 for p in prices],
        'low': [p - 2 for p in prices],
        'close': [p + 1 for p in prices],
        'volume': [10000 + i * 100 for i in range(50)]
    }, index=dates)

    return df

def main():
    """主函数"""
    print("=" * 60)
    print("缠论分析 Agent 使用示例")
    print("=" * 60)

    # 创建示例数据
    df = create_sample_data()
    print(f"\n创建了 {len(df)} 天的模拟K线数据")
    print(f"日期范围: {df.index[0]} 至 {df.index[-1]}")
    print(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")

    # 创建 Agent
    agent = ChanlunAgent()

    # 分析股票
    print("\n开始分析...")
    result = agent.analyze("000001", df)

    # 打印结果
    print("\n" + result['report'])

    # 打印信号详情
    print("\n" + "=" * 60)
    print("交易信号详情")
    print("=" * 60)

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

    print("\n" + "=" * 60)
    print("示例完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
