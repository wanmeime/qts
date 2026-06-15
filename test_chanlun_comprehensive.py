# -*- coding: utf-8 -*-
"""
缠论分析Agent综合测试
模拟分析上证指数、莲花控股、金风科技和自选股
"""

import sys
sys.path.insert(0, '/home/jiaod/qts/10-策略/缠论Agent')

import pandas as pd
import numpy as np
from datetime import datetime
from chanlun_agent import ChanlunAgent

def create_mock_data(stock_name, stock_code, days=100):
    """创建模拟K线数据"""
    np.random.seed(hash(stock_name) % 2**32)

    dates = pd.date_range('2025-01-01', periods=days, freq='D')

    # 根据不同股票创建不同的价格模式
    if stock_name == "上证指数":
        # 上证指数：先下跌后震荡
        base_price = 3000
        prices = []
        for i in range(days):
            if i < 30:  # 下跌段
                price = base_price - i * 10 + np.random.normal(0, 20)
            elif i < 60:  # 震荡段
                price = 2700 + np.sin(i * 0.2) * 100 + np.random.normal(0, 15)
            else:  # 上涨段
                price = 2700 + (i - 60) * 5 + np.random.normal(0, 25)
            prices.append(price)

    elif stock_name == "莲花控股":
        # 莲花控股：大幅波动后上涨
        base_price = 10
        prices = []
        for i in range(days):
            if i < 20:  # 快速下跌
                price = base_price - i * 0.3 + np.random.normal(0, 0.5)
            elif i < 40:  # 底部震荡
                price = 4 + np.sin(i * 0.3) * 1 + np.random.normal(0, 0.3)
            elif i < 70:  # 缓慢上涨
                price = 4 + (i - 40) * 0.1 + np.random.normal(0, 0.4)
            else:  # 加速上涨
                price = 7 + (i - 70) * 0.2 + np.random.normal(0, 0.3)
            prices.append(price)

    elif stock_name == "金风科技":
        # 金风科技：V型反转
        base_price = 20
        prices = []
        for i in range(days):
            if i < 40:  # 下跌
                price = base_price - i * 0.2 + np.random.normal(0, 0.8)
            elif i < 60:  # 底部
                price = 12 + np.sin(i * 0.2) * 1.5 + np.random.normal(0, 0.6)
            else:  # 反转上涨
                price = 12 + (i - 60) * 0.15 + np.random.normal(0, 0.5)
            prices.append(price)

    elif stock_name == "贵州茅台":
        # 贵州茅台：稳步上涨
        base_price = 1800
        prices = []
        for i in range(days):
            price = base_price + i * 2 + np.sin(i * 0.1) * 50 + np.random.normal(0, 30)
            prices.append(price)

    elif stock_name == "五粮液":
        # 五粮液：震荡上行
        base_price = 150
        prices = []
        for i in range(days):
            price = base_price + i * 0.5 + np.sin(i * 0.15) * 10 + np.random.normal(0, 5)
            prices.append(price)

    elif stock_name == "宁德时代":
        # 宁德时代：先跌后涨
        base_price = 200
        prices = []
        for i in range(days):
            if i < 30:
                price = base_price - i * 2 + np.random.normal(0, 5)
            elif i < 60:
                price = 140 + np.sin(i * 0.2) * 15 + np.random.normal(0, 8)
            else:
                price = 140 + (i - 60) * 1.5 + np.random.normal(0, 6)
            prices.append(price)

    else:
        # 默认：随机波动
        base_price = 50
        prices = [base_price]
        for i in range(1, days):
            change = np.random.normal(0, 0.02) * prices[-1]
            prices.append(prices[-1] + change)

    # 创建DataFrame
    df = pd.DataFrame({
        'open': prices,
        'high': [p + abs(np.random.normal(0, 1)) for p in prices],
        'low': [p - abs(np.random.normal(0, 1)) for p in prices],
        'close': [p + np.random.normal(0, 0.5) for p in prices],
        'volume': [1000000 + i * 10000 + np.random.randint(-50000, 50000) for i in range(days)]
    }, index=dates)

    return df

def analyze_stock(agent, stock_code, stock_name, kline_data):
    """分析单个股票"""
    print(f"\n{'='*70}")
    print(f"分析标的: {stock_name} ({stock_code})")
    print(f"{'='*70}")

    if kline_data is None or kline_data.empty:
        print("❌ 无法获取K线数据")
        return None

    print(f"K线数据: {len(kline_data)} 条")
    print(f"数据时间范围: {kline_data.index[0].strftime('%Y-%m-%d')} 至 {kline_data.index[-1].strftime('%Y-%m-%d')}")

    try:
        result = agent.analyze(stock_code, kline_data, use_multi_level=False)

        # 输出分析结果
        print(f"\n📊 缠论分析结果:")
        print(f"{'='*70}")

        # 缠论结构
        chanlun = result['chanlun']
        if chanlun:
            print(f"\n🎯 缠论结构:")
            print(f"  分型数量: {len(chanlun.get('fractals', []))}")
            print(f"  笔数量: {len(chanlun.get('bis', []))}")
            print(f"  线段数量: {len(chanlun.get('xian_duans', []))}")
            print(f"  中枢数量: {len(chanlun.get('zhong_shus', []))}")

            # 显示最近的中枢
            if chanlun.get('zhong_shus'):
                last_zs = chanlun['zhong_shus'][-1]
                print(f"  最近中枢: [{last_zs.low:.2f}, {last_zs.high:.2f}]")

        # MACD状态
        macd = result['macd']
        if macd:
            print(f"\n📈 MACD状态:")
            # 处理不同类型的MACD值
            dif = macd.get('dif', 'N/A')
            dea = macd.get('dea', 'N/A')
            macd_val = macd.get('macd', 'N/A')

            # 尝试格式化数值
            try:
                dif_str = f"{float(dif):.4f}" if isinstance(dif, (int, float)) else str(dif)
                dea_str = f"{float(dea):.4f}" if isinstance(dea, (int, float)) else str(dea)
                macd_str = f"{float(macd_val):.4f}" if isinstance(macd_val, (int, float)) else str(macd_val)
            except:
                dif_str = str(dif)
                dea_str = str(dea)
                macd_str = str(macd_val)

            print(f"  DIF: {dif_str}")
            print(f"  DEA: {dea_str}")
            print(f"  MACD柱: {macd_str}")
            print(f"  背驰信号: {'有' if macd.get('divergences') else '无'}")

        # 买卖点信号
        signal = result['signal']
        print(f"\n🚦 交易信号:")
        print(f"  信号类型: {signal['type']}")
        print(f"  信号强度: {signal['strength']:.2f}")
        if signal['reasons']:
            print(f"  信号原因:")
            for reason in signal['reasons']:
                print(f"    - {reason}")

        # 关键价位
        if signal['key_prices']:
            print(f"\n💰 关键价位:")
            for key, value in signal['key_prices'].items():
                print(f"  {key}: {value:.2f}")

        # 止损位
        if signal['stop_loss']:
            print(f"  止损位: {signal['stop_loss']:.2f}")

        # 分析报告
        print(f"\n📝 分析报告:")
        print(result['report'])

        return result

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("🚀 开始缠论分析Agent综合测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 初始化缠论分析Agent
    agent = ChanlunAgent()

    # 定义测试标的
    test_stocks = [
        ("000001", "上证指数"),
        ("600187", "莲花控股"),  # 假设代码
        ("002202", "金风科技"),  # 假设代码
        ("600519", "贵州茅台"),
        ("000858", "五粮液"),
        ("300750", "宁德时代")
    ]

    # 分析每个标的
    results = []
    for stock_code, stock_name in test_stocks:
        print(f"\n📥 创建 {stock_name} 的模拟K线数据...")
        kline_data = create_mock_data(stock_name, stock_code)

        result = analyze_stock(agent, stock_code, stock_name, kline_data)
        if result:
            results.append((stock_name, stock_code, result))

    # 输出总结
    print(f"\n{'='*70}")
    print("📊 测试总结")
    print(f"{'='*70}")

    for stock_name, stock_code, result in results:
        signal = result['signal']
        print(f"{stock_name} ({stock_code}): {signal['type']} (强度: {signal['strength']:.2f})")

    print(f"\n✅ 测试完成")
    print(f"成功分析 {len(results)}/{len(test_stocks)} 个标的")

if __name__ == "__main__":
    main()