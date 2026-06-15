# -*- coding: utf-8 -*-
"""
缠论分析系统重写验证测试

测试用例：
1. 基础数据结构和枚举
2. K线包含处理
3. 分型识别
4. 笔的识别
5. 中枢识别
6. 买卖点识别
7. 多级别分析
8. 信号输出
9. 完整流程（模拟数据）
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chanlun_core import (
    ChanlunCore, Direction, FractalType, BuySellType,
    ProcessedKline, Fractal, Bi, ZhongShu, BuySellPoint
)
from multi_level import MultiLevelAnalysis, MultiLevelResult, LevelAnalysis
from signal_output import SignalOutput, Signal
from chanlun_agent import ChanlunAgent


def create_uptrend_data(n=30):
    """创建上涨趋势数据"""
    dates = pd.date_range('2025-01-01', periods=n, freq='D')
    base = 100
    opens = []
    highs = []
    lows = []
    closes = []
    for i in range(n):
        # 震荡上涨
        noise = np.sin(i * 0.5) * 3
        trend = i * 0.8
        o = base + trend + noise
        h = o + abs(np.random.normal(0, 1.5))
        l = o - abs(np.random.normal(0, 1.5))
        c = o + np.random.normal(0, 1)
        opens.append(round(o, 2))
        highs.append(round(max(o, h, c), 2))
        lows.append(round(min(o, l, c), 2))
        closes.append(round(c, 2))
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }, index=dates)


def create_vshape_data():
    """
    创建V形反转数据：先下跌后上涨（确定性，无随机噪声）

    结构：顶部 → 底部 → 顶部，确保能识别出顶分型和底分型。
    每根K线的high/low有足够的波动差异，避免包含。
    """
    # 明确的V形走势：高位震荡 → 下跌 → 底部 → 上涨 → 高位
    # 用 high 价格序列来规划走势
    high_seq = [
        # 开头有顶分型（高→低→高→低）
        115, 112, 118, 110, 105,
        # 下跌段
        100, 95, 90, 85, 80,
        # 底部（低→高→低 形成底分型）
        78, 75, 77,
        # 上涨段
        82, 87, 92, 97, 102, 107, 112, 117, 122,
    ]
    n = len(high_seq)
    dates = pd.date_range('2025-01-01', periods=n, freq='D')
    opens = []
    highs = []
    lows = []
    closes = []
    for i, h in enumerate(high_seq):
        l = h - 5  # low 比 high 低5块，确保不被包含
        o = h - 1
        c = h - 2
        opens.append(round(o, 2))
        highs.append(round(h, 2))
        lows.append(round(l, 2))
        closes.append(round(c, 2))
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }, index=dates)


def create_oscillation_data():
    """创建震荡盘整数据"""
    n = 50
    dates = pd.date_range('2025-01-01', periods=n, freq='D')
    opens = []
    highs = []
    lows = []
    closes = []
    for i in range(n):
        base = 100 + np.sin(i * 0.4) * 10
        o = base
        h = o + abs(np.random.normal(0, 2))
        l = o - abs(np.random.normal(0, 2))
        c = o + np.random.normal(0, 1.5)
        opens.append(round(o, 2))
        highs.append(round(max(o, h, c), 2))
        lows.append(round(min(o, l, c), 2))
        closes.append(round(c, 2))
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }, index=dates)


def test_chanlun_core():
    """测试缠论核心算法"""
    print("=" * 60)
    print("测试1: 缠论核心算法")
    print("=" * 60)

    core = ChanlunCore()

    # 测试数据
    df = create_vshape_data()

    # 完整分析
    result = core.analyze(df)

    # 验证
    assert len(result['processed_klines']) > 0, "处理后K线应不为空"
    print(f"  处理后K线数: {len(result['processed_klines'])}")

    assert len(result['fractals']) >= 2, f"分型数应>=2，实际={len(result['fractals'])}"
    print(f"  分型数: {len(result['fractals'])}")

    top_count = sum(1 for f in result['fractals'] if f.type == FractalType.TOP)
    bottom_count = sum(1 for f in result['fractals'] if f.type == FractalType.BOTTOM)
    print(f"    顶分型: {top_count}, 底分型: {bottom_count}")

    assert len(result['bis']) >= 1, f"笔数应>=1，实际={len(result['bis'])}"
    print(f"  笔数: {len(result['bis'])}")

    for bi in result['bis']:
        dir_cn = "上涨" if bi.direction == Direction.UP else "下跌"
        print(f"    {dir_cn}: {bi.start_fractal.price:.2f} → {bi.end_fractal.price:.2f} (高={bi.high:.2f}, 低={bi.low:.2f})")

    print(f"  中枢数: {len(result['zhong_shus'])}")
    for zs in result['zhong_shus']:
        dir_cn = "上涨" if zs.direction == Direction.UP else "下跌"
        print(f"    中枢[{dir_cn}]: [{zs.low:.2f}, {zs.high:.2f}]")

    print(f"  买卖点数: {len(result['buy_sell_points'])}")
    for p in result['buy_sell_points']:
        print(f"    {p.type.value}: {p.price:.2f} (强度={p.strength:.2f})")

    if result['continuation_fractals']:
        cf = result['continuation_fractals']
        dir_cn = "上涨" if cf.direction == Direction.UP else "下跌"
        print(f"  中继分型: {cf.count}次（{dir_cn}笔中）")

    # 验证笔的交替性
    bis = result['bis']
    for i in range(1, len(bis)):
        assert bis[i].direction != bis[i-1].direction, \
            f"笔应交替: 笔{i-1}={bis[i-1].direction}, 笔{i}={bis[i].direction}"

    # 验证中枢重叠
    for zs in result['zhong_shus']:
        assert zs.high > zs.low, f"中枢应有重叠: high={zs.high}, low={zs.low}"

    print("  [PASS] 缠论核心算法测试通过")
    print()
    return result


def test_multi_level():
    """测试多级别分析"""
    print("=" * 60)
    print("测试2: 多级别分析")
    print("=" * 60)

    daily_df = create_vshape_data()

    ml = MultiLevelAnalysis()
    result = ml.analyze_multi_level("TEST001", daily_df)

    assert isinstance(result, MultiLevelResult), "返回类型应为MultiLevelResult"
    assert result.daily is not None, "日线分析结果不应为空"
    assert result.daily.level.value == "daily", "应为日线级别"

    print(f"  日线笔方向: {'上涨' if result.daily.current_bi_direction == Direction.UP else '下跌' if result.daily.current_bi_direction == Direction.DOWN else '未知'}")
    print(f"  日线在中枢中: {result.daily.in_zhong_shu}")
    print(f"  日线笔数: {result.daily.total_bis}")
    print(f"  日线买点数: {len(result.daily.buy_points)}")
    print(f"  日线卖点数: {len(result.daily.sell_points)}")
    print(f"  综合信号: {result.overall_signal}")

    signal_cn = {"buy": "买入", "sell": "卖出", "hold": "观望", "wait": "等待"}
    print(f"  综合信号(中文): {signal_cn.get(result.overall_signal, result.overall_signal)}")

    print()
    print("  日线分析摘要:")
    print(result.summary)

    print("  [PASS] 多级别分析测试通过")
    print()
    return result


def test_signal_output():
    """测试信号输出"""
    print("=" * 60)
    print("测试3: 信号输出")
    print("=" * 60)

    df = create_vshape_data()
    core = ChanlunCore()
    result = core.analyze(df)

    ml = MultiLevelAnalysis()
    ml_result = ml.analyze_multi_level("TEST001", df)

    so = SignalOutput()
    signal = so.generate_signal(result, ml_result, current_price=80.0)

    assert isinstance(signal, Signal), "返回类型应为Signal"
    assert signal.signal_type in ("buy", "sell", "hold", "stop_loss", "error"), \
        f"信号类型无效: {signal.signal_type}"

    print(f"  信号类型: {signal.signal_type}")
    print(f"  信号强度: {signal.strength:.2f}")
    print(f"  当前价格: {signal.current_price}")
    print(f"  第一止损线: {signal.stop_loss_first}")
    print(f"  第二止损线: {signal.stop_loss_strong}")
    print(f"  原因: {signal.reasons}")

    # 测试格式化
    formatted = so.format_signal(signal)
    assert len(formatted) > 0, "格式化输出不应为空"
    print()
    print(formatted)

    print("  [PASS] 信号输出测试通过")
    print()
    return signal


def test_agent_full():
    """测试Agent完整流程"""
    print("=" * 60)
    print("测试4: Agent完整流程")
    print("=" * 60)

    df = create_vshape_data()

    agent = ChanlunAgent()
    result = agent.analyze("TEST001", df)

    assert 'stock_code' in result, "结果应包含stock_code"
    assert 'chanlun' in result, "结果应包含chanlun"
    assert 'multi_level' in result, "结果应包含multi_level"
    assert 'signal' in result, "结果应包含signal"
    assert 'report' in result, "结果应包含report"

    assert result['stock_code'] == "TEST001"
    assert isinstance(result['signal'], Signal)
    assert len(result['report']) > 0

    print(f"  股票代码: {result['stock_code']}")
    print(f"  信号类型: {result['signal'].signal_type}")
    print(f"  报告长度: {len(result['report'])}字符")
    print()
    print(result['report'])

    print("  [PASS] Agent完整流程测试通过")
    print()


def test_stop_loss():
    """测试止损规则"""
    print("=" * 60)
    print("测试5: 止损规则")
    print("=" * 60)

    df = create_vshape_data()
    core = ChanlunCore()
    chanlun_result = core.analyze(df)

    ml = MultiLevelAnalysis()
    ml_result = ml.analyze_multi_level("TEST001", df)

    so = SignalOutput()

    # 场景1: 当前价高于买点 → 不触发止损
    buy_points = [p for p in chanlun_result['buy_sell_points'] if 'buy' in p.type.value]
    if buy_points:
        high_price = buy_points[-1].price + 5
        signal_high = so.generate_signal(chanlun_result, ml_result, current_price=high_price)
        print(f"  场景1: 价格={high_price:.2f} > 买点={buy_points[-1].price:.2f}")
        print(f"    信号: {signal_high.signal_type}")
        assert signal_high.signal_type != "stop_loss", "高价位不应触发止损"

    # 场景2: 当前价低于买点 → 触发第一止损
    if buy_points:
        low_price = buy_points[-1].price - 2
        signal_low = so.generate_signal(chanlun_result, ml_result, current_price=low_price)
        print(f"  场景2: 价格={low_price:.2f} < 买点={buy_points[-1].price:.2f}")
        print(f"    信号: {signal_low.signal_type}")
        # 如果没有一买止损线，会触发第一止损
        if signal_low.stop_loss_first and low_price < signal_low.stop_loss_first:
            assert signal_low.signal_type == "stop_loss", "低于买点应触发止损"

    # 场景3: 当前价低于一买 → 触发强止损
    buy1_points = [p for p in chanlun_result['buy_sell_points'] if p.type == BuySellType.BUY1]
    if buy1_points:
        very_low = buy1_points[-1].price - 5
        signal_strong = so.generate_signal(chanlun_result, ml_result, current_price=very_low)
        print(f"  场景3: 价格={very_low:.2f} < 一买={buy1_points[-1].price:.2f}")
        print(f"    信号: {signal_strong.signal_type}")
        if very_low < signal_strong.stop_loss_strong:
            assert signal_strong.signal_type == "stop_loss", "低于一买应触发强止损"

    print("  [PASS] 止损规则测试通过")
    print()


def test_include_relation():
    """测试包含关系处理"""
    print("=" * 60)
    print("测试6: 包含关系处理")
    print("=" * 60)

    # 构造包含关系数据
    data = {
        'open':  [100, 102, 101, 103, 105],
        'high':  [105, 104, 106, 104, 108],
        'low':   [98,  99,  97,  100, 103],
        'close': [103, 100, 104, 102, 107],
    }
    df = pd.DataFrame(data, index=pd.date_range('2025-01-01', periods=5, freq='D'))

    core = ChanlunCore()
    processed = core.process_klines(df)

    print(f"  原始K线数: {len(df)}")
    print(f"  处理后K线数: {len(processed)}")

    for k in processed:
        print(f"    K线{k.index}: high={k.high:.2f}, low={k.low:.2f}, 合并{k.raw_count}根")

    # 处理后K线数应该 <= 原始K线数（因为包含被合并了）
    assert len(processed) <= len(df), "处理后K线数应<=原始数"

    print("  [PASS] 包含关系处理测试通过")
    print()


def test_known_pattern():
    """测试已知形态：标准的下跌-反弹-下跌-上涨结构"""
    print("=" * 60)
    print("测试7: 已知形态验证")
    print("=" * 60)

    # 构造一个明确的形态：
    # 下跌(100→80) → 反弹(80→95) → 下跌(95→75) → 反弹(75→90) → 下跌(90→70)
    # 应该能识别出二买（75 > 80? 不满足）
    # 改成: 下跌(100→80) → 反弹(80→95) → 下跌(95→85) → 二买(85 > 80)

    n = 60
    dates = pd.date_range('2025-01-01', periods=n, freq='D')
    opens = []
    highs = []
    lows = []
    closes = []

    # 构造明确的价格走势
    prices = [
        # 下跌1: 100→80 (10根)
        100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80,
        # 反弹1: 80→95 (8根)
        82, 84, 87, 90, 92, 93, 94, 95,
        # 下跌2: 95→85 (8根) - 二买：85 > 80
        93, 91, 89, 87, 86, 85.5, 85,
        # 反弹2: 85→98 (8根)
        87, 89, 91, 93, 95, 96, 97, 98,
        # 下跌3: 98→90 (8根)
        97, 96, 94, 93, 92, 91, 90.5, 90,
        # 反弹3: 90→105 (8根)
        92, 94, 96, 98, 100, 102, 103, 105,
    ]

    n = len(prices)
    dates = pd.date_range('2025-01-01', periods=n, freq='D')
    for p in prices:
        opens.append(p)
        highs.append(p + 2)
        lows.append(p - 2)
        closes.append(p + 0.5)

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }, index=dates)

    core = ChanlunCore()
    result = core.analyze(df)

    print(f"  处理后K线数: {len(result['processed_klines'])}")
    print(f"  分型数: {len(result['fractals'])}")
    print(f"  笔数: {len(result['bis'])}")
    print(f"  中枢数: {len(result['zhong_shus'])}")

    for bi in result['bis']:
        dir_cn = "上涨" if bi.direction == Direction.UP else "下跌"
        print(f"    {dir_cn}: {bi.start_fractal.price:.2f} → {bi.end_fractal.price:.2f}")

    print(f"  买卖点数: {len(result['buy_sell_points'])}")
    for p in result['buy_sell_points']:
        type_cn = "买" if "buy" in p.type.value else "卖"
        print(f"    {p.type.value}: {p.price:.2f} (强度={p.strength:.2f})")

    # Agent完整测试
    agent = ChanlunAgent()
    agent_result = agent.analyze("KNOWN", df)
    print()
    print("  Agent报告:")
    print(agent_result['report'])

    print("  [PASS] 已知形态验证完成")
    print()


def main():
    """运行所有测试"""
    print("=" * 60)
    print("缠论分析系统重写验证测试")
    print("=" * 60)
    print()

    try:
        test_chanlun_core()
        test_multi_level()
        test_signal_output()
        test_agent_full()
        test_stop_loss()
        test_include_relation()
        test_known_pattern()

        print("=" * 60)
        print("所有测试通过!")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
