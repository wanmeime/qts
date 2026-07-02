import urllib.request, json, sys, time, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import asdict

sys.path.insert(0, str(Path("/home/jiaod/qts/10-策略/缠论Agent")))
sys.path.insert(0, str(Path("/home/jiaod/qts/50-盯盘")))

from chanlun_core import ChanlunCore
from signal_templates import BottomFractalSignal, BuySellLabel, SignalStatus
from state_store import StateStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("full_market_scan")

_CST = timezone(timedelta(hours=8))

import pandas as pd

def get_full_market_codes():
    resp = urllib.request.urlopen("http://172.31.144.1:8890/api/stocks/list", timeout=15)
    data = json.loads(resp.read())
    raw = data.get("stocks", [])
    codes = [c for c in raw if not c.startswith("688") and not c.startswith("8") and not c.startswith("920")]
    logger.info(f"QMT返回{data.get('count',0)}只, 过滤后{len(codes)}只")
    return codes

def load_kline_from_qmt(code, days=365):
    qmt_code = code if "." in code else (f"{code}.SH" if code.startswith(('6','9')) else f"{code}.SZ")
    url = f"http://172.31.144.1:8890/api/kline?code={qmt_code}&period=1d&count={min(days, 365)}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        result = json.loads(resp.read())
        kline_data = result.get("data", [])
        if len(kline_data) < 30:
            return None
        df = pd.DataFrame(kline_data)
        df["date"] = pd.to_datetime(df["time"], format="%Y%m%d")
        df = df.set_index("date")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df.tail(days).reset_index(drop=False).rename(columns={"index": "date"})
    except:
        return None

def get_name_from_qmt(code):
    qmt_code = code if "." in code else (f"{code}.SH" if code.startswith(('6','9')) else f"{code}.SZ")
    try:
        resp = urllib.request.urlopen(f"http://172.31.144.1:8890/api/name?code={qmt_code}", timeout=5)
        data = json.loads(resp.read())
        return data.get("name", code)
    except:
        return code

def run_full_market_scan():
    analysis_time = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now(_CST).strftime("%Y-%m-%d")
    logger.info(f"=== 全市场扫描开始: {analysis_time} ===")

    codes = get_full_market_codes()
    store = StateStore()

    all_signals = []
    scanned = 0
    errors = 0
    start_time = time.time()

    for i, raw_code in enumerate(codes):
        try:
            bare_code = raw_code.replace(".SH", "").replace(".SZ", "")
            daily_df = load_kline_from_qmt(raw_code, days=365)
            if daily_df is None or len(daily_df) < 60:
                continue

            core = ChanlunCore()
            core.process_klines(daily_df[["open", "high", "low", "close"]])
            core.find_fractals()
            core.find_bis()
            core.find_zhong_shus()
            if len(daily_df) > 30:
                core._calc_macd(daily_df["close"].astype(float))
            core.find_buy_sell_points()

            from static_analyzer import generate_daily_signals
            stock_name = get_name_from_qmt(raw_code)
            signals = generate_daily_signals(bare_code, stock_name, core, daily_df, today_str)

            if signals:
                for sig in signals:
                    all_signals.append(sig)
                logger.info(f"  [{i+1}/{len(codes)}] {bare_code} {stock_name} - 发现买点!")

            scanned += 1
            if (i + 1) % 200 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed * 60
                logger.info(f"进度: {i+1}/{len(codes)} 已扫描 {scanned} 只, 发现 {len(all_signals)} 个信号, 速度 {rate:.0f}只/分钟")

        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning(f"  {raw_code} 分析失败: {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== 全市场扫描完成 ===")
    logger.info(f"扫描: {scanned} 只, 失败: {errors} 只, 耗时: {elapsed:.0f}秒")
    logger.info(f"发现买点信号: {len(all_signals)} 个")

    # 写入DB
    if all_signals:
        logger.info(f"写入 {len(all_signals)} 条信号到 DB...")
        store.clear_signal_templates(keep_history=True)
        store.save_signal_templates(all_signals)
        logger.info("DB 写入完成")

    # 打印汇总
    if all_signals:
        print("\n" + "=" * 80)
        print(f"全市场扫描买点信号 ({len(all_signals)} 个) - 已写入 watchdog.db")
        print("=" * 80)
        print(f"{'代码':<8} {'名称':<10} {'类型':<8} {'分型价':<10} {'突破位':<10} {'止损位':<10}")
        print("-" * 80)
        for s in sorted(all_signals, key=lambda x: x.stock_code):
            label = s.buy_label.value if hasattr(s.buy_label, 'value') else str(s.buy_label)
            print(f"{s.stock_code:<8} {s.stock_name:<10} {label:<8} {s.fractal_price:<10} {s.third_high:<10} {s.stop_loss:<10}")
    else:
        print("\n全市场扫描完成，今日无新的买点信号。")

    return all_signals

if __name__ == "__main__":
    run_full_market_scan()
