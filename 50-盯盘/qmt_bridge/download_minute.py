# -*- coding: utf-8 -*-
"""
全市场分钟K线下载工具（QMT/Windows 端）

通过 xtquant 下载 15分钟 / 5分钟 K线数据，
保存为 CSV 文件到共享目录，供 WSL Linux 端使用。

用法（Windows cmd）:
    python D:\qmt_bridge\download_minute.py --scale 15
    python D:\qmt_bridge\download_minute.py --scale 5
"""
import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("qmt_download")

# K线缓存目录（Linux WSL 路径，通过 \\wsl.localhost 访问）
WSL_HOME = r"\\wsl.localhost\Ubuntu\home\jiaod\qts"
KLINE_DIRS = {
    15: Path(WSL_HOME) / "00-研究" / "数据源" / "缓存" / "kline_15m",
    5: Path(WSL_HOME) / "00-研究" / "数据源" / "缓存" / "kline_5m",
}
START_DATE = "20241220"
END_DATE = datetime.now().strftime("%Y%m%d")

# 如果 WSL 网络路径不可用，回退到本地临时目录
LOCAL_FALLBACK = Path(r"D:\qmt_bridge\data")


def get_stock_list() -> list:
    """从 kline_day 目录获取全市场股票列表"""
    day_dir = Path(WSL_HOME) / "00-研究" / "数据源" / "缓存" / "kline_day"
    if not day_dir.exists():
        logger.warning(f"kline_day 目录不存在: {day_dir}")
        return []
    codes = sorted(f.stem for f in day_dir.glob("*.csv"))
    logger.info(f"共 {len(codes)} 只股票")
    return codes


def download_minute_data(code: str, period: str, start: str, end: str, out_dir: Path) -> int:
    """
    通过 xtquant 下载单只股票的分钟线

    Args:
        code: QMT格式代码 (sh600519 / sz000063)
        period: 周期 (5m / 15m)
        start: 起始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD
        out_dir: 输出目录

    Returns:
        下载行数
    """
    csv_path = out_dir / f"{code}.csv"
    
    # 检查已有数据
    existing_end = None
    if csv_path.exists():
        try:
            lines = csv_path.read_text().strip().split("\n")
            if len(lines) > 1:
                existing_end = lines[-1].split(",")[0][:10].replace("-", "")
        except Exception:
            pass

    # 如果需要的数据已经存在，跳过
    if existing_end and existing_end >= end:
        return 0

    try:
        from xtquant.xtdata import download_history_data, get_market_data
        
        # 下载数据
        logger.debug(f"  下载 {code} {period} {start}~{end}")
        download_history_data(
            stock_code=code,
            period=period,
            start_time=start,
            end_time=end,
        )
        time.sleep(0.1)

        # 读取数据
        data = get_market_data(
            field_list=[],
            stock_list=[code],
            period=period,
            start_time=start,
            end_time=end,
            dividend_type='front',
        )

        if not data or 'close' not in data:
            return 0

        close_df = data['close']
        if close_df.empty:
            return 0

        # 转换为 DataFrame
        import pandas as pd
        times = close_df.columns.tolist()
        records = []
        for t in times:
            row = {
                'date': str(t),
                'open': float(data['open'][t].iloc[0]) if t in data['open'] else 0,
                'high': float(data['high'][t].iloc[0]) if t in data['high'] else 0,
                'low': float(data['low'][t].iloc[0]) if t in data['low'] else 0,
                'close': float(data['close'][t].iloc[0]),
                'volume': int(data['volume'][t].iloc[0]) if t in data['volume'] else 0,
                'amount': float(data['amount'][t].iloc[0]) if t in data['amount'] else 0,
            }
            records.append(row)

        if not records:
            return 0

        # 追加写入 CSV
        mode = 'a' if csv_path.exists() else 'w'
        with open(csv_path, 'a') as f:
            if mode == 'w':
                f.write("date,open,high,low,close,volume,amount\n")
            for r in records:
                date_str = r['date'].replace(" ", "T") if " " in r['date'] else r['date']
                if existing_end and date_str[:10].replace("-", "") <= existing_end:
                    continue  # 跳过已存在的数据
                f.write(f"{date_str},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']},{r['amount']}\n")

        return len(records)

    except Exception as e:
        logger.error(f"{code} 失败: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="全市场分钟K线下载(QMT)")
    parser.add_argument("--scale", type=str, default="15m", choices=["5m", "15m"], help="K线周期")
    parser.add_argument("--start", default=START_DATE, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=END_DATE, help="结束日期 YYYYMMDD")
    parser.add_argument("--max-stocks", type=int, default=0, help="测试用:最多下载数")
    args = parser.parse_args()

    period = args.scale
    scale_num = int(period.replace("m", ""))
    out_dir = KLINE_DIRS.get(scale_num, LOCAL_FALLBACK / f"kline_{period}")

    # 尝试创建输出目录
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        out_dir = LOCAL_FALLBACK / f"kline_{period}"
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"WSL路径不可用，回退到: {out_dir}")

    codes = get_stock_list()
    if args.max_stocks > 0:
        codes = codes[:args.max_stocks]

    logger.info(f"周期: {period}, 股票: {len(codes)} 只")
    logger.info(f"区间: {args.start} ~ {args.end}")
    logger.info(f"输出: {out_dir}")

    total = 0
    skipped = 0
    failed = 0
    start_ts = time.time()

    for i, code in enumerate(codes, 1):
        n = download_minute_data(code, period, args.start, args.end, out_dir)
        if n > 0:
            total += n
            logger.info(f"[{i}/{len(codes)}] {code}: +{n} 条")
        else:
            skipped += 1

        # 每100只报告进度
        if i % 100 == 0:
            elapsed = time.time() - start_ts
            rate = i / elapsed * 60
            logger.info(f"进度 {i}/{len(codes)}, 耗时 {elapsed:.0f}s, 速率 {rate:.0f} 只/分钟")

    elapsed = time.time() - start_ts
    logger.info(f"=== 完成 ===")
    logger.info(f"新增: {total} 条")
    logger.info(f"跳过: {skipped} 只")
    logger.info(f"失败: {failed} 只")
    logger.info(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    main()
