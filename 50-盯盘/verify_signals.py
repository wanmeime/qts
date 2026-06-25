#!/usr/bin/env python3
"""验证系统买卖点信号"""
import sys
sys.path.insert(0, '10-策略/缠论Agent')
import pandas as pd
import requests as req
import json

def fetch_kline(code, days=120, scale=240):
    symbol = f"sh{code}" if code.startswith('6') else f"sz{code}"
    url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days+30}"
    resp = req.get(url, timeout=10)
    text = resp.text
    start = text.index('[')
    end = text.rindex(']') + 1
    data = json.loads(text[start:end])
    df = pd.DataFrame(data)
    df = df.rename(columns={'day':'date','open':'open','close':'close','high':'high','low':'low','volume':'volume'})
    for col in ['open','close','high','low','volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.tail(days).reset_index(drop=True)

from chanlun_core import ChanlunCore

stocks = [
    ("300124", "汇川技术"),
    ("000001", "平安银行"),
    ("002230", "科大讯飞"),
]

for code, name in stocks:
    df = fetch_kline(code)
    df.index = pd.to_datetime(df['date'])
    core = ChanlunCore()
    state = core.analyze(df, level='daily')

    print(f"{'='*60}")
    print(f"  {name}({code})  现价={df['close'].iloc[-1]:.2f}  趋势={state['trend']}")
    print(f"{'='*60}")
    print(f"  笔: {state['bis']}  中枢: {state['zhong_shus']}")

    print(f"  笔序列:")
    for i, b in enumerate(core.bis):
        d = '↑' if b.direction.value == 1 else '↓'
        print(f"    {d}  {b.start_fractal.timestamp[:10]}({b.start_fractal.price:.2f}) -> {b.end_fractal.timestamp[:10]}({b.end_fractal.price:.2f})")

    zs_text = []
    for zs in core.zhong_shus:
        zs_text.append(f"[{zs.low:.2f}, {zs.high:.2f}]")
    print(f"  中枢区间: {', '.join(zs_text) if zs_text else '无'}")

    if core.buy_sell_points:
        print(f"  买卖点:")
        for p in core.buy_sell_points:
            print(f"    {p.type.value:6s}  价格={p.price:>8.2f}  日期={p.timestamp[:10]}")
    else:
        print(f"  买卖点: 无")

    # MACD面积比较
    print(f"  MACD面积(绝对值累加):")
    close = df['close'].astype(float)
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = 2 * (dif - dea)

    for b in core.bis:
        if b.direction.value == -1:
            si = min(b.start_fractal.index, len(macd)-1)
            ei = min(b.end_fractal.index, len(macd)-1)
            area = macd.iloc[si:ei+1].abs().sum()
            dir_mark = "↓"
        else:
            si = min(b.start_fractal.index, len(macd)-1)
            ei = min(b.end_fractal.index, len(macd)-1)
            area = macd.iloc[si:ei+1].abs().sum()
            dir_mark = "↑"
        print(f"    {dir_mark} 终价{b.end_fractal.price:>7.2f}  MACD面积={area:.2f}")

    print()
