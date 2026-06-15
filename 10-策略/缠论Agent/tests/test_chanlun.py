# -*- coding: utf-8 -*-
"""
缠论分析单元测试

测试内容：
1. 分型识别
2. 笔划分
3. 中枢识别
4. 买卖点识别
5. MACD 分析
"""

import sys
import os
import pandas as pd
import numpy as np

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun_core import ChanlunCore, FractalType, Direction, BuySellType
from macd_analysis import MACDAnalysis, MACDSignal

def create_test_data():
    """创建测试用的K线数据"""
    # 创建一个简单的下跌-上涨-下跌走势
    dates = pd.date_range('2023-01-01', periods=50, freq='D')

    # 生成价格序列
    prices = []
    # 下跌段
    for i in range(10):
        prices.append(100 - i * 2)
    # 上涨段
    for i in range(10):
        prices.append(80 + i * 2)
    # 下跌段
    for i in range(10):
        prices.append(100 - i * 2)
    # 上涨段
    for i in range(10):
        prices.append(80 + i * 2)
    # 最后一段
    for i in range(10):
        prices.append(100 - i * 1)

    df = pd.DataFrame({
        'open': prices,
        'high': [p + 1 for p in prices],
        'low': [p - 1 for p in prices],
        'close': [p + 0.5 for p in prices],
        'volume': [1000] * 50
    }, index=dates)

    return df

def test_kline_processing():
    """测试K线包含处理"""
    print("测试 K线包含处理...")
    chanlun = ChanlunCore()
    df = create_test_data()

    processed = chanlun.process_klines(df)

    # 验证处理后的K线数量应该少于原始数量
    assert len(processed) <= len(df), "处理后的K线数量应该少于原始数量"

    # 验证每根K线的高点 >= 低点
    for kline in processed:
        assert kline.high >= kline.low, f"K线高点应该大于等于低点: {kline.high} < {kline.low}"

    print(f"  原始K线数: {len(df)}, 处理后: {len(processed)}")
    print("  K线包含处理测试通过")

def test_fractal_detection():
    """测试分型识别"""
    print("\n测试 分型识别...")
    chanlun = ChanlunCore()
    df = create_test_data()

    # 处理K线
    chanlun.process_klines(df)

    # 识别分型
    fractals = chanlun.find_fractals()

    # 验证找到分型
    assert len(fractals) > 0, "应该找到分型"

    # 验证分型类型
    top_count = sum(1 for f in fractals if f.type == FractalType.TOP)
    bottom_count = sum(1 for f in fractals if f.type == FractalType.BOTTOM)

    print(f"  找到 {len(fractals)} 个分型: {top_count} 个顶分型, {bottom_count} 个底分型")

    # 验证顶分型的高点高于相邻K线
    for f in fractals:
        if f.type == FractalType.TOP:
            idx = f.index
            if 0 < idx < len(chanlun.processed_klines) - 1:
                prev_high = chanlun.processed_klines[idx - 1].high
                next_high = chanlun.processed_klines[idx + 1].high
                assert f.price > prev_high and f.price > next_high, \
                    f"顶分型应该高于相邻K线: {f.price} vs {prev_high}, {next_high}"

    print("  分型识别测试通过")

def test_bi_division():
    """测试笔划分"""
    print("\n测试 笔划分...")
    chanlun = ChanlunCore()
    df = create_test_data()

    # 完整流程
    chanlun.process_klines(df)
    chanlun.find_fractals()
    bis = chanlun.find_bis()

    # 验证笔的方向交替
    if len(bis) > 1:
        for i in range(1, len(bis)):
            assert bis[i].direction != bis[i-1].direction, \
                f"笔的方向应该交替: {bis[i-1].direction} -> {bis[i].direction}"

    print(f"  找到 {len(bis)} 笔")

    # 验证笔的最小间距
    for bi in bis:
        gap = abs(bi.end_index - bi.start_index)
        assert gap >= 4, f"笔的间距应该至少为4: {gap}"

    print("  笔划分测试通过")

def test_zhong_shu_detection():
    """测试中枢识别"""
    print("\n测试 中枢识别...")
    chanlun = ChanlunCore()
    df = create_test_data()

    # 完整流程
    chanlun.process_klines(df)
    chanlun.find_fractals()
    chanlun.find_bis()
    zhong_shus = chanlun.find_zhong_shus()

    print(f"  找到 {len(zhong_shus)} 个中枢")

    # 验证中枢
    for zs in zhong_shus:
        # 中枢上沿应该高于下沿
        assert zs.high > zs.low, f"中枢上沿应该高于下沿: {zs.high} <= {zs.low}"

        # 至少包含3笔
        assert len(zs.bis) >= 3, f"中枢应该至少包含3笔: {len(zs.bis)}"

        print(f"    中枢区间: [{zs.low:.2f}, {zs.high:.2f}], 包含 {len(zs.bis)} 笔")

    print("  中枢识别测试通过")

def test_buy_sell_points():
    """测试买卖点识别"""
    print("\n测试 买卖点识别...")
    chanlun = ChanlunCore()
    df = create_test_data()

    # 完整流程
    chanlun.process_klines(df)
    chanlun.find_fractals()
    chanlun.find_bis()
    chanlun.find_zhong_shus()
    points = chanlun.find_buy_sell_points()

    print(f"  找到 {len(points)} 个买卖点")

    for p in points:
        print(f"    {p.type.value}: {p.price:.2f} (强度: {p.strength:.2f})")

    print("  买卖点识别测试通过")

def test_macd_analysis():
    """测试 MACD 分析"""
    print("\n测试 MACD 分析...")
    macd = MACDAnalysis()
    df = create_test_data()

    # 计算 MACD
    result = macd.analyze(df)

    # 验证 MACD 数据
    assert len(result['macd_data']) == len(df), "MACD 数据长度应该与原始数据相同"

    # 验证金叉/死叉
    crosses = result['crosses']
    print(f"  找到 {len(crosses)} 个交叉信号")

    for c in crosses:
        print(f"    {c.signal.value}: {c.timestamp}")

    # 验证背驰
    divergences = result['divergences']
    print(f"  找到 {len(divergences)} 个背驰信号")

    for d in divergences:
        print(f"    {d.signal.value}: {d.timestamp}")

    print("  MACD 分析测试通过")

def test_complete_analysis():
    """测试完整分析流程"""
    print("\n测试 完整分析流程...")
    chanlun = ChanlunCore()
    df = create_test_data()

    # 完整分析
    result = chanlun.analyze(df)

    # 验证结果包含所有必要字段
    assert 'processed_klines' in result, "结果应该包含 processed_klines"
    assert 'fractals' in result, "结果应该包含 fractals"
    assert 'bis' in result, "结果应该包含 bis"
    assert 'zhong_shus' in result, "结果应该包含 zhong_shus"
    assert 'buy_sell_points' in result, "结果应该包含 buy_sell_points"

    print(f"  处理后K线: {len(result['processed_klines'])}")
    print(f"  分型: {len(result['fractals'])}")
    print(f"  笔: {len(result['bis'])}")
    print(f"  中枢: {len(result['zhong_shus'])}")
    print(f"  买卖点: {len(result['buy_sell_points'])}")

    print("  完整分析流程测试通过")

def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("缠论分析单元测试")
    print("=" * 50)

    try:
        test_kline_processing()
        test_fractal_detection()
        test_bi_division()
        test_zhong_shu_detection()
        test_buy_sell_points()
        test_macd_analysis()
        test_complete_analysis()

        print("\n" + "=" * 50)
        print("所有测试通过!")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n测试失败: {e}")
        raise
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    run_all_tests()
