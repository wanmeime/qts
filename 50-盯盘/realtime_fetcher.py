#!/usr/bin/env python3
"""
实时行情抓取模块
支持东方财富、新浪、腾讯三个数据源
"""
import requests
import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class RealtimeFetcher:
    """实时行情抓取器"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def fetch_batch(self, codes, source: str = "eastmoney") -> Dict[str, Dict]:
        """
        批量获取实时行情。

        Args:
            codes: 股票代码列表或元组，如 ["600519", "000858"]
            source: 数据源 (eastmoney/sina/tencent)

        Returns:
            {code: {name, price, change_pct, open, high, low, volume, amount, ...}}
        """
        if isinstance(codes, tuple):
            codes = list(codes)
        fetchers = {
            "eastmoney": self._fetch_eastmoney,
            "sina": self._fetch_sina,
            "tencent": self._fetch_tencent,
        }
        fetcher = fetchers.get(source, self._fetch_eastmoney)
        try:
            return fetcher(codes)
        except Exception as e:
            logger.warning(f"{source} 获取失败: {e}，尝试备用源")
            fallback = "sina" if source != "sina" else "tencent"
            return fetchers[fallback](codes)

    def fetch_indices(self, index_codes: Optional[Dict[str, str]] = None) -> Dict[str, Dict]:
        """
        获取大盘指数实时行情。

        Args:
            index_codes: {代码: 名称} 字典，默认使用主要指数

        Returns:
            {code: {name, price, change_pct, ...}}
        """
        if index_codes is None:
            index_codes = {
                "000001": "上证指数",
                "399001": "深证成指",
                "000300": "沪深300",
                "399006": "创业板指",
            }

        codes = list(index_codes.keys())
        result = {}

        # 指数代码需要加前缀
        prefixed = {}
        for code in codes:
            if code.startswith("000") or code.startswith("880"):
                prefixed[f"sh{code}"] = code
            else:
                prefixed[f"sz{code}"] = code

        # 用新浪接口获取指数
        try:
            url = f"https://hq.sinajs.cn/list={','.join(prefixed.keys())}"
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            resp.encoding = "gbk"

            for line in resp.text.strip().split("\n"):
                match = re.search(r'var hq_str_(\w+)="(.*)"', line)
                if not match:
                    continue
                symbol = match.group(1)
                data = match.group(2)
                if not data:
                    continue

                parts = data.split(",")
                if len(parts) < 4:
                    continue

                code = prefixed.get(symbol, symbol)
                try:
                    result[code] = {
                        "code": code,
                        "name": index_codes.get(code, parts[0]),
                        "price": float(parts[3]),
                        "open": float(parts[1]),
                        "prev_close": float(parts[2]),
                        "high": float(parts[4]),
                        "low": float(parts[5]),
                        "volume": float(parts[8]) if len(parts) > 8 else 0,
                        "amount": float(parts[9]) if len(parts) > 9 else 0,
                        "change_pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
                        "time": f"{parts[30]} {parts[31]}" if len(parts) > 31 else "",
                    }
                except (ValueError, IndexError) as e:
                    logger.warning(f"解析指数 {code} 失败: {e}")
        except Exception as e:
            logger.error(f"获取指数行情失败: {e}")

        return result

    def _fetch_eastmoney(self, codes) -> Dict[str, Dict]:
        """东方财富实时行情"""
        if isinstance(codes, tuple):
            codes = list(codes)
        result = {}

        # 构建筛选条件
        secids = []
        for code in codes:
            if code.startswith("6") or code.startswith("9"):
                secids.append(f"1.{code}")
            else:
                secids.append(f"0.{code}")

        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18",
            "secids": ",".join(secids),
        }

        resp = self.session.get(url, params=params, timeout=self.timeout)
        data = resp.json()

        if data.get("data") and data["data"].get("diff"):
            for item in data["data"]["diff"]:
                code = item.get("f12", "")
                if not code:
                    continue
                result[code] = {
                    "code": code,
                    "name": item.get("f14", ""),
                    "price": item.get("f2", 0),
                    "change_pct": item.get("f3", 0),
                    "change_amt": item.get("f4", 0),
                    "volume": item.get("f5", 0),
                    "amount": item.get("f6", 0),
                    "amplitude": item.get("f7", 0),
                    "turnover": item.get("f8", 0),
                    "high": item.get("f15", 0),
                    "low": item.get("f16", 0),
                    "open": item.get("f17", 0),
                    "prev_close": item.get("f18", 0),
                    "source": "eastmoney",
                }

        return result

    def _fetch_sina(self, codes) -> Dict[str, Dict]:
        """新浪实时行情"""
        if isinstance(codes, tuple):
            codes = list(codes)
        result = {}

        # 转换代码格式
        symbols = []
        code_map = {}
        for code in codes:
            if code.startswith("6") or code.startswith("9"):
                sym = f"sh{code}"
            else:
                sym = f"sz{code}"
            symbols.append(sym)
            code_map[sym] = code

        url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
        headers = {"Referer": "https://finance.sina.com.cn"}
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        resp.encoding = "gbk"

        for line in resp.text.strip().split("\n"):
            match = re.search(r'var hq_str_(\w+)="(.*)"', line)
            if not match:
                continue
            symbol = match.group(1)
            data = match.group(2)
            if not data:
                continue

            parts = data.split(",")
            if len(parts) < 10:
                continue

            code = code_map.get(symbol, symbol)
            try:
                prev_close = float(parts[2])
                price = float(parts[3])
                result[code] = {
                    "code": code,
                    "name": parts[0],
                    "price": price,
                    "open": float(parts[1]),
                    "prev_close": prev_close,
                    "high": float(parts[4]),
                    "low": float(parts[5]),
                    "volume": float(parts[8]),
                    "amount": float(parts[9]),
                    "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0,
                    "time": f"{parts[30]} {parts[31]}" if len(parts) > 31 else "",
                    "source": "sina",
                }
            except (ValueError, IndexError) as e:
                logger.warning(f"解析 {code} 失败: {e}")

        return result

    def _fetch_tencent(self, codes: List[str]) -> Dict[str, Dict]:
        """腾讯实时行情"""
        result = {}

        symbols = []
        code_map = {}
        for code in codes:
            if code.startswith("6") or code.startswith("9"):
                sym = f"sh{code}"
            else:
                sym = f"sz{code}"
            symbols.append(sym)
            code_map[sym] = code

        url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.encoding = "gbk"

        for line in resp.text.strip().split(";"):
            line = line.strip()
            if not line or "~" not in line:
                continue

            parts = line.split("~")
            if len(parts) < 35:
                continue

            symbol = line.split("=")[0].split("_")[-1].strip('"')
            code = code_map.get(symbol, symbol)

            try:
                result[code] = {
                    "code": code,
                    "name": parts[1],
                    "price": float(parts[3]),
                    "prev_close": float(parts[4]),
                    "open": float(parts[5]),
                    "volume": float(parts[6]) * 100,  # 腾讯单位是手
                    "amount": float(parts[37]) * 10000 if len(parts) > 37 else 0,
                    "high": float(parts[33]),
                    "low": float(parts[34]),
                    "change_pct": float(parts[32]),
                    "time": parts[30] if len(parts) > 30 else "",
                    "source": "tencent",
                }
            except (ValueError, IndexError) as e:
                logger.warning(f"解析 {code} 失败: {e}")

        return result


# ============================================================
# QMT 行情源（通过 Windows 转发服务）
# ============================================================

QMT_BRIDGE_HOST = "http://172.31.144.1:8890"


class QmtFetcher:
    """
    QMT 行情抓取器

    通过 Windows QMT 转发服务获取实时行情。
    使用方式与 RealtimeFetcher 兼容（相同的 fetch_batch / fetch_indices 接口）。
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.base_url = QMT_BRIDGE_HOST
        self._code_cache = {}  # 缓存股票名称

    def fetch_batch(self, codes, source: str = "") -> Dict[str, Dict]:
        """
        批量获取实时行情（通过 QMT），大列表自动分片（每片 1000 只）

        Args:
            codes: 股票代码列表或元组，如 ["300450", "000001"]
            source: 忽略（兼容接口）

        Returns:
            {code: {name, price, change_pct, open, high, low, volume, amount, ...}}
        """
        if not codes:
            return {}
        if isinstance(codes, tuple):
            codes = list(codes)

        # 转为 QMT 格式 (300450.SZ / 000001.SH)
        qmt_codes = []
        code_map = {}  # qmt_code -> original_code
        for c in codes:
            if "." in c:
                bare = c.split(".")[0]
            else:
                bare = c
            if bare.startswith(("6", "9")):
                qc = f"{bare}.SH"
            else:
                qc = f"{bare}.SZ"
            qmt_codes.append(qc)
            code_map[qc] = bare

        # 分片：每片最多 1000 只，避免 URL 过长
        chunk_size = 1000
        all_results = {}
        for i in range(0, len(qmt_codes), chunk_size):
            chunk = qmt_codes[i:i + chunk_size]
            try:
                url = f"{self.base_url}/api/quotes/batch"
                resp = self.session.get(url, params={"codes": ",".join(chunk)},
                                        timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                for qc, d in data.items():
                    orig_code = code_map.get(qc, qc.replace(".SH", "").replace(".SZ", ""))
                    all_results[orig_code] = {
                        "code": orig_code,
                        "name": d.get("name", orig_code),
                        "price": d.get("price", 0),
                        "change_pct": d.get("change_pct", 0),
                        "open": d.get("open", 0),
                        "high": d.get("high", 0),
                        "low": d.get("low", 0),
                        "volume": d.get("volume", 0),
                        "amount": d.get("amount", 0),
                        "prev_close": d.get("lastClose", 0),
                        "source": "qmt",
                    }
            except requests.ConnectionError:
                logger.warning("QMT 桥接服务不可达")
                return all_results if all_results else {}
            except Exception as e:
                logger.warning(f"QMT 获取行情分片 {i//chunk_size} 失败: {e}")
                continue
        return all_results

    def fetch_indices(self, index_codes: Optional[Dict[str, str]] = None) -> Dict[str, Dict]:
        """
        获取大盘指数实时行情（通过 QMT）

        Args:
            index_codes: {代码: 名称} 字典

        Returns:
            {code: {name, price, change_pct, ...}}
        """
        if index_codes is None:
            index_codes = {
                "000001": "上证指数",
                "399001": "深证成指",
                "000300": "沪深300",
                "399006": "创业板指",
            }

        # QMT 指数代码
        qmt_codes = []
        for c in index_codes.keys():
            if c.startswith("000") or c.startswith("880"):
                qmt_codes.append(f"{c}.SH")
            else:
                qmt_codes.append(f"{c}.SZ")

        try:
            url = f"{self.base_url}/api/quotes/batch"
            resp = self.session.get(url, params={"codes": ",".join(qmt_codes)},
                                    timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            result = {}
            for qc, d in data.items():
                code = qc.replace(".SH", "").replace(".SZ", "")
                result[code] = {
                    "code": code,
                    "name": index_codes.get(code, code),
                    "price": d.get("price", 0),
                    "change_pct": d.get("change_pct", 0),
                    "open": d.get("open", 0),
                    "high": d.get("high", 0),
                    "low": d.get("low", 0),
                    "volume": d.get("volume", 0),
                    "source": "qmt",
                }
            return result
        except Exception as e:
            logger.warning(f"QMT 获取指数失败: {e}")
            return {}


def is_trading_hours() -> bool:
    """判断当前是否为交易时段 (9:15-15:05)"""
    now = datetime.now(_CST)
    weekday = now.weekday()

    # 周末不交易
    if weekday >= 5:
        return False

    current_time = now.hour * 100 + now.minute
    return 915 <= current_time <= 1505


def get_market_status() -> str:
    """获取市场状态"""
    now = datetime.now(_CST)
    weekday = now.weekday()

    if weekday >= 5:
        return "休市 (周末)"

    current_time = now.hour * 100 + now.minute

    if current_time < 915:
        return "盘前"
    elif current_time <= 930:
        return "集合竞价"
    elif current_time <= 1130:
        return "上午交易中"
    elif current_time < 1300:
        return "午间休市"
    elif current_time <= 1457:
        return "下午交易中"
    elif current_time <= 1500:
        return "收盘集合竞价"
    elif current_time <= 1505:
        return "已收盘"
    else:
        return "盘后"
