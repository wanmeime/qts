# -*- coding: utf-8 -*-
"""
缠论分析Agent测试脚本
测试多个标的的缠论分析
"""

import sys
sys.path.insert(0, '/home/jiaod/qts/10-策略/缠论Agent')

import akshare as ak
import pandas as pd
from datetime import datetime
from chanlun_agent import ChanlunAgent

def get_stock_code_by_name(stock_name):
    """根据股票名称查找股票代码"""
    try:
        df = ak.stock_zh_a_spot_em()
        result = df[df['名称'].str.contains(stock_name, na=False)]
        if not result.empty:
            return result.iloc[0]['代码']
        return None
    except Exception as e:
        print(f"查找股票代码失败: {e}")
        return None

def get_kline_data(symbol, start_date="20250101", end_date="20260607"):
    """获取K线数据"""
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                               start_date=start_date, end_date=end_date)
        # 重命名列以匹配缠论分析要求
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount'
        })
        # 转换日期格式
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        return df
    except Exception as e:
        print(f"获取K线数据失败 {symbol}: {e}")
        return None

def analyze_stock(agent, stock_code, stock_name, kline_data):
    """分析单个股票"""
    print(f"\n{'='*60}")
    print(f"分析标的: {stock_name} ({stock_code})")
    print(f"{'='*60}")

    if kline_data is None or kline_data.empty:
        print("❌ 无法获取K线数据")
        return None

    print(f"K线数据: {len(kline_data)} 条")
    print(f"数据时间范围: {kline_data.index[0].strftime('%Y-%m-%d')} 至 {kline_data.index[-1].strftime('%Y-%m-%d')}")

    try:
        result = agent.analyze(stock_code, kline_data, use_multi_level=False)

        # 输出分析结果
        print(f"\n📊 缠论分析结果:")
        print(f"{'='*60}")

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
            print(f"  DIF: {macd.get('dif', 'N/A'):.4f}")
            print(f"  DEA: {macd.get('dea', 'N/A'):.4f}")
            print(f"  MACD柱: {macd.get('macd', 'N/A'):.4f}")
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
    print("🚀 开始缠论分析Agent测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 初始化缠论分析Agent
    agent = ChanlunAgent()

    # 定义测试标的
    test_stocks = [
        ("000001", "上证指数"),  # 上证指数
    ]

    # 查找莲花控股和金风科技的股票代码
    print("\n🔍 查找股票代码...")
    lotus_code = get_stock_code_by_name("莲花控股")
    jinfeng_code = get_stock_code_by_name("金风科技")

    if lotus_code:
        test_stocks.append((lotus_code, "莲花控股"))
        print(f"✅ 莲花控股: {lotus_code}")
    else:
        print("❌ 未找到莲花控股")

    if jinfeng_code:
        test_stocks.append((jinfeng_code, "金风科技"))
        print(f"✅ 金风科技: {jinfeng_code}")
    else:
        print("❌ 未找到金风科技")

    # 从自选股中随机挑选2-3只A股
    try:
        # 这里假设有一些自选股，如果没有可以跳过
        # 实际使用时可以从配置文件中读取
        print("\n📌 从自选股中挑选标的...")
        # 这里可以添加自选股列表
        watchlist = [
            ("600519", "贵州茅台"),
            ("000858", "五粮液"),
            ("300750", "宁德时代")
        ]

        # 随机挑选2-3只
        import random
        selected_stocks = random.sample(watchlist, min(3, len(watchlist)))
        test_stocks.extend(selected_stocks)
        print(f"✅ 已添加 {len(selected_stocks)} 只自选股")

    except Exception as e:
        print(f"⚠️  添加自选股失败: {e}")

    # 分析每个标的
    results = []
    for stock_code, stock_name in test_stocks:
        print(f"\n📥 获取 {stock_name} 的K线数据...")
        kline_data = get_kline_data(stock_code)

        result = analyze_stock(agent, stock_code, stock_name, kline_data)
        if result:
            results.append((stock_name, stock_code, result))

    # 输出总结
    print(f"\n{'='*60}")
    print("📊 测试总结")
    print(f"{'='*60}")

    for stock_name, stock_code, result in results:
        signal = result['signal']
        print(f"{stock_name} ({stock_code}): {signal['type']} (强度: {signal['strength']:.2f})")

    print(f"\n✅ 测试完成")
    print(f"成功分析 {len(results)}/{len(test_stocks)} 个标的")

if __name__ == "__main__":
    main()