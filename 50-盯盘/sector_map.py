# -*- coding: utf-8 -*-
"""
本地板块映射表
=============
股票代码 → {行业, 概念} 的本地缓存。
通过 akshare 预热生成，之后 Dashboard 直接查此表。
"""
import json
from pathlib import Path

SECTOR_MAP_FILE = Path(__file__).parent / "sector_map.json"


def _try_get_sector_akshare(code: str) -> dict:
    """尝试从 akshare 获取板块信息（可能因网络超时而失败）"""
    try:
        import akshare as ak
        import pandas as pd

        # 方法1: stock_board_industry_name_em + stock_board_concept_name_em
        # 获取行业和概念列表，再查个股属于哪个
        
        # 更简单：用 stock_individual_info_em 获取个股行业
        df = ak.stock_individual_info_em(symbol=code)
        if df is not None and len(df) > 0:
            industry = ""
            for _, row in df.iterrows():
                if "行业" in str(row.iloc[0]):
                    industry = row.iloc[1]
                    break
            return {"行业": industry, "概念": ""}
    except Exception:
        pass
    return {"行业": "", "概念": ""}


def build_sector_map(codes: list) -> dict:
    """为股票列表生成板块映射"""
    result = {}
    for code in codes:
        info = _try_get_sector_akshare(code)
        result[code] = info
    return result


def load_sector_map() -> dict:
    """加载已缓存的板块映射"""
    if SECTOR_MAP_FILE.exists():
        try:
            with open(SECTOR_MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_sector_map(data: dict):
    """保存板块映射"""
    SECTOR_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SECTOR_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_sector(code: str) -> dict:
    """获取单个股票的板块信息（查本地缓存）"""
    mapping = load_sector_map()
    return mapping.get(code, {"行业": "", "概念": ""})


if __name__ == "__main__":
    import sys
    # 预热：从 watchlist.json 读取所有股票代码生成映射
    watchlist_path = Path(__file__).parent.parent / "00-研究" / "自选股" / "watchlist.json"
    if watchlist_path.exists():
        with open(watchlist_path, "r", encoding="utf-8") as f:
            watchlist = json.load(f)
        codes = [w.get("code", "") for w in watchlist if isinstance(w, dict) and w.get("code")]
        codes = [c for c in codes if c and not c.startswith("399") and not c.startswith("880")]
        print(f"从 watchlist.json 读取到 {len(codes)} 只股票，开始获取板块信息...")
        
        mapping = {}
        for i, code in enumerate(codes):
            info = _try_get_sector_akshare(code)
            mapping[code] = info
            if info["行业"]:
                print(f"  [{i+1}/{len(codes)}] {code}: {info['行业']}")
            else:
                print(f"  [{i+1}/{len(codes)}] {code}: 未获取到")
        
        save_sector_map(mapping)
        print(f"\n已生成 {len(mapping)} 条板块映射 → {SECTOR_MAP_FILE}")
    else:
        print(f"未找到 watchlist.json")
