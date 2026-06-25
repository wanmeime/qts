#!/usr/bin/env python3
"""
全市场分钟级别 K 线数据下载工具

通过新浪接口下载 15分钟 / 5分钟 K线数据，
从 2024-12-20 到最新交易日。

用法:
    python3 tools/download_minute_kline.py --scale 15    # 下载15分钟线
    python3 tools/download_minute_kline.py --scale 5     # 下载5分钟线
    python3 tools/download_minute_kline.py --scale 15 --max-stocks 100  # 测试前100只
"""
import sys
import os
import json
import time
import logging
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_kline")

PROJECT_ROOT = Path(__file__).parent.parent
KLINE_DAY_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_day"
KLINE_15M_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_15m"
KLINE_5M_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_5m"

SCALE_MAP = {15: KLINE_15M_DIR, 5: KLINE_5M_DIR}
SINA_URL = "https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData"
MAX_RETRIES = 3
BATCH_SIZE = 500  # 新浪接口单次最多拉取条数

# 起始日期
START_DATE = "2024-12-20"


def get_stock_list() -> list:
    """从 kline_day 目录获取全市场股票代码列表"""
    codes = []
    for f in sorted(KLINE_DAY_DIR.glob("*.csv")):
        code = f.stem  # sh600519
        codes.append(code)
    return codes


def sina_kline(code: str, scale: int, datalen: int) -> list:
    """调用新浪 K线接口，返回原始 JSON 列表"""
    url = f"{SINA_URL}?symbol={code}&scale={scale}&ma=no&datalen={datalen}"
    for retry in range(MAX_RETRIES):
        try:
            r = requests.get(url, timeout=15)
            text = r.text
            start = text.index("[")
            end = text.rindex("]") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError, requests.RequestException) as e:
            if retry < MAX_RETRIES - 1:
                time.sleep(1)
                continue
            logger.warning(f"{code} scale={scale} 失败: {e}")
            return []


def download_stock(code: str, scale: int, out_dir: Path) -> int:
    """
    下载单只股票的分钟K线
    从 START_DATE 开始，分批向后拉取直到最新
    返回下载条数；如果文件已存在且完整则跳过
    """
    csv_path = out_dir / f"{code}.csv"

    # 检查已有数据，断点续传
    existing_end = None
    if csv_path.exists():
        try:
            with open(csv_path, "r") as f:
                lines = f.readlines()
            if len(lines) > 1:
                last_line = lines[-1].strip()
                existing_end = last_line.split(",")[0]  # 日期时间
        except Exception:
            pass

    # 分批向后拉取
    all_rows = []
    seen = set()
    cursor = ""
    max_empty_runs = 3
    empty_run = 0

    for batch in range(50):  # 最多50批（500*50=25000条，约5年数据量）
        # 构建游标：如果 cursor 为空，从 START_DATE 开始拉
        params = f"symbol={code}&scale={scale}&ma=no&datalen={BATCH_SIZE}"
        if cursor:
            params += f"&datalen={BATCH_SIZE}&offset={cursor}"

        url = f"{SINA_URL}?{params}"
        rows = sina_kline(code, scale, BATCH_SIZE)

        if not rows:
            empty_run += 1
            if empty_run >= max_empty_runs:
                break
            continue
        empty_run = 0

        # 过滤：只保留 START_DATE 之后的
        new_count = 0
        for row in rows:
            day_str = row.get("day", "")[:10]
            if day_str < START_DATE:
                continue
            # 去重
            key = row["day"]
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
            new_count += 1

        if new_count == 0:
            empty_run += 1
            if empty_run >= max_empty_runs:
                break
            continue

        # 更新游标：取最后一笔的时间
        cursor = rows[-1]["day"]
        time.sleep(0.05)  # 节流

    if not all_rows:
        return 0

    # 如果已有数据，合并追加
    if existing_end:
        # 只保留新数据（> existing_end 的数据）
        all_rows = [r for r in all_rows if r["day"] > existing_end]

    if not all_rows:
        return 0

    # 追加写入 CSV
    is_new = not csv_path.exists()
    with open(csv_path, "a") as f:
        if is_new:
            f.write("date,open,high,low,close,volume,amount\n")
        for row in all_rows:
            f.write(f"{row['day']},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']},{row['amount']}\n")

    return len(all_rows)


def main():
    parser = argparse.ArgumentParser(description="全市场分钟K线下载")
    parser.add_argument("--scale", type=int, choices=[5, 15], required=True, help="K线周期(分钟)")
    parser.add_argument("--max-stocks", type=int, default=0, help="最多下载股票数(0=全部)")
    parser.add_argument("--workers", type=int, default=10, help="并发线程数")
    parser.add_argument("--stock-list", type=str, help="指定股票代码文件(每行一个)")
    args = parser.parse_args()

    out_dir = SCALE_MAP[args.scale]
    out_dir.mkdir(parents=True, exist_ok=True)

    # 获取股票列表
    if args.stock_list:
        with open(args.stock_list) as f:
            codes = [line.strip() for line in f if line.strip()]
    else:
        codes = get_stock_list()

    if args.max_stocks > 0:
        codes = codes[:args.max_stocks]

    logger.info(f"股票数: {len(codes)}")
    logger.info(f"周期: {args.scale}分钟")
    logger.info(f"输出目录: {out_dir}")
    logger.info(f"起始日期: {START_DATE}")
    logger.info(f"并发: {args.workers} 线程")

    total_new = 0
    total_skipped = 0
    total_failed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_stock, code, args.scale, out_dir): code
            for code in codes
        }

        done = 0
        for future in as_completed(futures):
            code = futures[future]
            done += 1
            try:
                n = future.result()
                if n > 0:
                    total_new += n
                    logger.info(f"[{done}/{len(codes)}] {code}: +{n} 条")
                else:
                    total_skipped += 1
                    if done % 100 == 0:
                        logger.info(f"[{done}/{len(codes)}] 进度...")
            except Exception as e:
                total_failed += 1
                logger.error(f"[{done}/{len(codes)}] {code}: 异常 {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== 完成 ===")
    logger.info(f"新增: {total_new} 条")
    logger.info(f"跳过: {total_skipped} 只")
    logger.info(f"失败: {total_failed} 只")
    logger.info(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    main()
