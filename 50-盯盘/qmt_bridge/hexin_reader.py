#!/usr/bin/env python3
"""
同花顺 .day 文件读取器（hd1.0格式）
"""
import struct, os
import pandas as pd
from pathlib import Path

# 同花顺数据目录
SZ_DAY_DIR = Path("/mnt/d/同花顺软件/同花顺/history/sznse/day/")
SH_DAY_DIR = Path("/mnt/d/同花顺软件/同花顺/history/shase/day/")

_cache = {}


def decode_price(b4: bytes) -> float:
    """同花顺hd1.0价格解码: LE_u32 & 0x00FFFFFF / 10000"""
    u32 = struct.unpack('<I', b4)[0]
    return round((u32 & 0x00FFFFFF) / 10000.0, 2)


def read_day_file(code: str) -> pd.DataFrame:
    """读取单只股票的日K线数据"""
    # 确定文件路径
    for day_dir in [SZ_DAY_DIR, SH_DAY_DIR]:
        fpath = day_dir / f"{code}.day"
        if fpath.exists():
            break
    else:
        return pd.DataFrame()

    with open(fpath, 'rb') as f:
        data = f.read()

    # 跳过文件头（使数据体为32的整数倍）
    for hdr in range(0, 256):
        if (len(data) - hdr) % 32 == 0:
            break

    body = data[hdr:]
    records = []
    for i in range(0, len(body), 32):
        rec = body[i:i+32]
        if len(rec) < 32:
            break
        date = struct.unpack('<I', rec[0:4])[0]
        if date < 19900000 or date > 20261231:
            continue
        records.append({
            'date': pd.Timestamp(f'{date//10000}-{date%10000//100:02d}-{date%100:02d}'),
            'open': decode_price(rec[4:8]),
            'high': decode_price(rec[8:12]),
            'low': decode_price(rec[12:16]),
            'close': decode_price(rec[16:20]),
            'volume': struct.unpack('<I', rec[24:28])[0],
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.sort_values('date').reset_index(drop=True)
    df = df.set_index('date')
    return df


def get_hexin_kline(code: str, days: int = 120) -> pd.DataFrame:
    """获取同花顺K线数据（带缓存）"""
    cache_key = f"{code}"
    if cache_key not in _cache:
        _cache[cache_key] = read_day_file(code)
    
    df = _cache[cache_key]
    if df.empty:
        return df
    
    return df.tail(days).copy()


def has_hexin_data(code: str) -> bool:
    """检查是否有该股票的同花顺数据"""
    return (SZ_DAY_DIR / f"{code}.day").exists() or (SH_DAY_DIR / f"{code}.day").exists()


def list_available_stocks() -> list:
    """列出所有可用的股票代码"""
    codes = []
    for d in [SZ_DAY_DIR, SH_DAY_DIR]:
        if d.exists():
            for f in os.listdir(d):
                if f.endswith('.day') and not f.startswith('1'):
                    codes.append(f.replace('.day', ''))
    return sorted(codes)
