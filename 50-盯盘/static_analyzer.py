# -*- coding: utf-8 -*-
"""
静态分析模块（盘后运行）

流程：
  1. 从 QMT 获取全市场 A 股代码（排除科创板 688 和北交所 8xx/920/BJ）
  2. 获取日线K线数据
  3. 调用缠论引擎分析每只股票
  4. 提取买卖点对应的分型数据 → 生成信号模板
  5. 对持仓股检查15分钟背驰段
  6. 生成持仓风控信号
  7. 写入 DB

不依赖实时行情，每天收盘后运行一次。
"""
import sys
import json
import logging
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests as req_lib
import pandas as pd

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
sys.path.insert(0, str(PROJECT_ROOT / "50-盯盘"))

from chanlun_core import (
    ChanlunCore, FractalType, Direction, BuySellType,
    BuySellPoint, Fractal, Bi,
)
from signal_templates import (
    BottomFractalSignal, TopFractalSignal,
    DivergenceZoneSignal, PositionRiskSignal,
    SignalStatus, DivergenceStatus, RiskLevel,
    BuySellLabel,
)
from state_store import StateStore
from realtime_fetcher import RealtimeFetcher

logger = logging.getLogger(__name__)

# 禁用 urllib 的 INFO/DEBUG 日志，防止刷屏
logging.getLogger("urllib").setLevel(logging.WARNING)

# ============================================================
# 基本面数据获取
# ============================================================

def fetch_financial_info(codes: List[str]) -> Dict[str, Dict]:
    """
    批量获取股票基本面信息（PE、PB、总市值等）

    优先使用 QMT 桥接（最稳定），回退东方财富 API。
    返回 {code: {pe, pb, mcap, name}}。
    亏损股的 PE 为负值。
    """
    if not codes:
        return {}

    result = {}

    # 1. 优先使用 QMT 桥接（Windows xtquant，数据最全最稳定）
    try:
        qmt_url = "http://172.31.144.1:8890/api/finance"
        # 分 200 只一批（QMT 接口无限制，但 URL 长度有限）
        for i in range(0, len(codes), 200):
            batch = codes[i:i + 200]
            params = {"codes": ",".join(batch)}
            resp = req_lib.get(qmt_url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    result.update(data)
        if result:
            logger.info(f"QMT 返回来 {len(result)} 只股票基本面数据")
            return result
        else:
            logger.warning("QMT 返回空数据，回退到东方财富 API")
    except Exception as e:
        logger.warning(f"QMT 桥接不可用 ({e})，回退到东方财富 API")

    # 2. 回退：东方财富 API（可能限流）
    logger.info("正在从东方财富获取基本面数据...")
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        secids = []
        for code in batch:
            if code.startswith("6") or code.startswith("9"):
                secids.append(f"1.{code}")
            else:
                secids.append(f"0.{code}")

        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f9,f23,f20,f14,f12",
            "secids": ",".join(secids),
        }
        try:
            resp = req_lib.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("data") and data["data"].get("diff"):
                for item in data["data"]["diff"]:
                    code = item.get("f12", "")
                    if not code or code in result:
                        continue
                    pe = item.get("f9")
                    if pe is not None:
                        try:
                            pe = float(pe)
                        except (ValueError, TypeError):
                            pe = None
                    pb_raw = item.get("f23")
                    try:
                        pb = float(pb_raw) if pb_raw is not None else None
                    except (ValueError, TypeError):
                        pb = None
                    mcap_raw = item.get("f20")
                    try:
                        mcap = float(mcap_raw) if mcap_raw is not None else None
                    except (ValueError, TypeError):
                        mcap = None
                    result[code] = {
                        "pe": pe,
                        "pb": pb,
                        "mcap": mcap,
                        "name": item.get("f14", code),
                    }
        except Exception as e:
            logger.warning(f"东方财富 API 请求失败 (batch {i}): {e}")

    logger.info(f"基本面数据获取完成: {len(result)} 只")
    return result


def should_filter_stock(info: dict) -> bool:
    """
    判断是否应该过滤该股票。

    过滤条件：亏损（PE<0 或无EPS）且无改善迹象的股票。
    但亏损在逐季改善的不过滤（潜在扭亏股）。

    判断依据：
      1. PE 为负 → 亏损
      2. PE 为 None 但 np_latest 为负 → 亏损（EPS<0无法算PE）
      3. 以上情况 + loss_narrowing=True → 亏损改善，不过滤
    """
    pe = info.get("pe")
    np_latest = info.get("np_latest")

    # 判断是否亏损
    is_losing = False
    if pe is not None and pe < 0:
        is_losing = True
    elif pe is None and np_latest is not None and np_latest < 0:
        is_losing = True

    if not is_losing:
        return False  # 盈利，不过滤

    # 亏损，检查是否在改善
    loss_narrowing = info.get("loss_narrowing")
    if loss_narrowing is True:
        return False  # 亏损收窄 → 潜在扭亏，不过滤

    return True  # 亏损且无改善，过滤

_CST = timezone(timedelta(hours=8))

# 路径常量
POSITION_FILE = PROJECT_ROOT / "40-执行" / "持仓" / "当前持仓.json"
WATCHLIST_FILE = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_6m"


# ============================================================
# 数据加载
# ============================================================

def load_positions() -> List[Dict]:
    """加载当前持仓"""
    if not POSITION_FILE.exists():
        logger.warning(f"持仓文件不存在: {POSITION_FILE}")
        return []
    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("持仓明细", [])
    except Exception as e:
        logger.error(f"加载持仓失败: {e}")
        return []


def load_watchlist() -> List[Dict]:
    """加载自选股列表"""
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("stocks", data.get("list", []))
    except Exception as e:
        logger.error(f"加载自选股失败: {e}")
        return []


def get_full_market_codes() -> List[str]:
    """
    从 QMT 获取全市场 A 股代码（裸代码，不含 .SH/.SZ 后缀）

    排除：
      - 科创板（688xxx）
      - 北交所（8xxxxx、920xxx、.BJ 后缀）
    """
    try:
        resp = urllib.request.urlopen("http://172.31.144.1:8890/api/stocks/list", timeout=15)
        data = json.loads(resp.read())
        raw = data.get("stocks", [])
        # 过滤：排除科创板(688)和北交所(8开头、920开头、.BJ后缀)
        codes = []
        for c in raw:
            if c.startswith("688") or c.startswith("8") or c.startswith("920") or c.endswith(".BJ"):
                continue
            # 去掉 .SH/.SZ 后缀，变成裸代码
            bare = c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            codes.append(bare)
        logger.info(f"QMT 返回 {data.get('count',0)} 只, 过滤后 {len(codes)} 只 A 股")
        return codes
    except Exception as e:
        logger.error(f"获取全市场代码失败: {e}")
        return []


def load_kline_data(code: str, days: int = 365, scale: int = 240) -> Optional[pd.DataFrame]:
    """
    加载K线数据（日线或15分钟）

    内联实现，避免与 watchdog.py 的循环导入。
    """
    # 仅日线支持本地数据源
    if scale == 240:
        # 0. 优先 QMT（与实时检测器一致，保证数据及时性）
        qmt_df = None
        try:
            qmt_code = f"{code}.SH" if code.startswith(('6', '9')) else f"{code}.SZ"
            url = f"http://172.31.144.1:8890/api/kline?code={qmt_code}&period=1d&count={min(days, 365)}"
            resp = req_lib.get(url, timeout=10)
            result = resp.json()
            qmt_data = result.get('data', [])
            if len(qmt_data) >= 30:
                qmt_df = pd.DataFrame(qmt_data)
                qmt_df['date'] = pd.to_datetime(qmt_df['time'], format='%Y%m%d')
                qmt_df = qmt_df.set_index('date')
                qmt_df = qmt_df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        except Exception:
            pass

        if qmt_df is not None and len(qmt_df) >= 30:
            return qmt_df.tail(days).reset_index(drop=False).rename(columns={"index": "date"})

        # 1. 回退：同花顺本地数据
        ths_df = None
        try:
            from qmt_bridge.hexin_reader import get_hexin_kline, has_hexin_data
            if has_hexin_data(code):
                ths_df = get_hexin_kline(code, days=days + 60)
        except Exception:
            pass

        # 2. 缓存（仅当无同花顺数据时）
        csv_df = None
        if ths_df is None or len(ths_df) < 30:
            csv_path = KLINE_CACHE_DIR / f"{code}.csv"
            if csv_path.exists():
                try:
                    csv_df = pd.read_csv(csv_path)
                    if "day" in csv_df.columns and "date" not in csv_df.columns:
                        csv_df = csv_df.rename(columns={"day": "date"})
                    if len(csv_df) >= 30:
                        csv_df = csv_df.set_index("date")
                        csv_df.index = pd.to_datetime(csv_df.index)
                except Exception:
                    pass

        # 3. 新浪接口
        sina_df = None
        try:
            if code.startswith("6") or code.startswith("9"):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
            url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 60}"
            resp = req_lib.get(url, timeout=10)
            text = resp.text
            start = text.index("[")
            end = text.rindex("]") + 1
            data = json.loads(text[start:end])
            if data:
                sina_df = pd.DataFrame(data)
                sina_df = sina_df.rename(columns={"day": "date"})
                for col in ["open", "close", "high", "low", "volume"]:
                    if col in sina_df.columns:
                        sina_df[col] = pd.to_numeric(sina_df[col], errors="coerce")
                sina_df["date"] = pd.to_datetime(sina_df["date"])
                sina_df = sina_df.set_index("date")
        except Exception:
            pass

        # 4. 合并数据
        if ths_df is not None and len(ths_df) >= 30 and sina_df is not None and len(sina_df) >= 30:
            common_dates = ths_df.index.intersection(sina_df.index)
            if len(common_dates) > 5:
                ratios = (ths_df.loc[common_dates, "close"] / sina_df.loc[common_dates, "close"]).values
                ratio = sum(ratios) / len(ratios)
            else:
                ratio = 1.0

            all_dates = sina_df.index.union(ths_df.index).sort_values()
            merged = pd.DataFrame(index=all_dates)
            for col in ["open", "high", "low", "close", "volume"]:
                if col in ths_df.columns:
                    merged[f"ths_{col}"] = ths_df[col]
                    merged[f"sina_{col}"] = sina_df[col] * ratio

            for col in ["open", "high", "low", "close"]:
                merged[col] = merged[f"ths_{col}"].fillna(merged[f"sina_{col}"])
            merged["volume"] = merged["ths_volume"].fillna(merged["sina_volume"]).fillna(0).astype(int)

            merged = merged.drop(columns=[c for c in merged.columns if c.startswith("ths_") or c.startswith("sina_")])
            merged = merged.dropna(subset=["close"])

            if len(merged) >= 30:
                return merged.tail(days).reset_index(drop=False).rename(columns={"index": "date"})

        if ths_df is not None and len(ths_df) >= 30:
            return ths_df.reset_index().tail(days).reset_index(drop=True)

        if csv_df is not None and len(csv_df) >= 30:
            return csv_df.tail(days).reset_index(drop=True)

    # 5. 仅有新浪（或非日线）
    try:
        if sina_df is not None and len(sina_df) >= 30:
            return sina_df.tail(days).reset_index(drop=False).rename(columns={"index": "date"})

        if code.startswith("6") or code.startswith("9"):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        url = f"https://quotes.sina.cn/cn/api/jsonp.php/=/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days + 30}"
        resp = req_lib.get(url, timeout=10)
        text = resp.text
        start = text.index("[")
        end = text.rindex("]") + 1
        data = json.loads(text[start:end])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.rename(columns={"day": "date"})
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.debug(f"获取 {code} K线(scale={scale})失败: {e}")
        return pd.DataFrame()


# ============================================================
# 信号模板生成
# ============================================================

def _buy_type_from_point(bp: BuySellPoint) -> Optional[BuySellLabel]:
    """将 BuySellType 转为信号模板的 BuySellLabel"""
    mapping = {
        BuySellType.BUY1: BuySellLabel.BUY1,
        BuySellType.BUY2: BuySellLabel.BUY2,
        BuySellType.BUY3: BuySellLabel.BUY3,
        BuySellType.SECONDARY_BUY: BuySellLabel.SECONDARY_BUY,
    }
    return mapping.get(bp.type)


def _sell_type_from_point(bp: BuySellPoint) -> Optional[BuySellLabel]:
    mapping = {
        BuySellType.SELL1: BuySellLabel.SELL1,
        BuySellType.SELL2: BuySellLabel.SELL2,
        BuySellType.SELL3: BuySellLabel.SELL3,
    }
    return mapping.get(bp.type)


def _find_fractal_for_point(
    core: ChanlunCore,
    bp: BuySellPoint,
) -> Optional[Fractal]:
    """在 core.fractals 中找与买卖点对应的分型"""
    for f in core.fractals:
        if f.index == bp.index:
            return f
    return None


def _is_buy_point(bp: BuySellPoint) -> bool:
    return bp.type in (BuySellType.BUY1, BuySellType.BUY2,
                       BuySellType.BUY3, BuySellType.SECONDARY_BUY)


def _is_sell_point(bp: BuySellPoint) -> bool:
    return bp.type in (BuySellType.SELL1, BuySellType.SELL2, BuySellType.SELL3)


# ============================================================
# 日线信号模板提取
# ============================================================

def generate_daily_signals(
    stock_code: str,
    stock_name: str,
    core: ChanlunCore,
    daily_df: pd.DataFrame,
    analysis_date: str,
    is_position: bool = False,
) -> List[object]:
    """
    从缠论分析结果中提取日线分型信号模板

    遍历 core.buy_sell_points，为每个买卖点找到对应的分型，
    生成 BottomFractalSignal（买点）或 TopFractalSignal（卖点）。

    策略过滤条件：
      - 只保留第三根K线为最新日K线的分型（昨天收盘刚形成的）
      - 买点信号需要成交量 > 近5日均量 × 1.5
    """
    signals = []
    seen = set()  # 同一个分型只生成一个信号

    # 策略要求：只监控昨天刚形成第三根K线的底分型/顶分型
    # 更早的分型已被后续走势验证或被覆盖，盯它没有意义
    # 第三根K线位置 = fractal.index + 1（在 processed_klines 中）

    # 成交量检查：计算近5日均量
    vol = daily_df['volume'].astype(float)
    avg_vol_5 = vol.tail(5).mean()
    latest_vol = vol.iloc[-1]
    vol_ratio = latest_vol / avg_vol_5 if avg_vol_5 > 0 else 0

    for bp in core.buy_sell_points:
        fractal = _find_fractal_for_point(core, bp)
        if fractal is None:
            continue

        # 策略：只监控昨天刚形成第三根K线的分型（盘中待验证）
        # 判断方式：第三根K线必须是 processed_klines 中的最后一根
        # （即最新完成的日K线，昨天收盘的那根）
        third_kline_idx = fractal.index + 1
        last_kline_idx = len(core.processed_klines) - 1
        if third_kline_idx != last_kline_idx:
            continue  # 第三根K线不是最新K线，跳过

        # 去重：同一个分型只输出一个信号
        if fractal.index in seen:
            continue
        seen.add(fractal.index)

        if _is_buy_point(bp):
            # 策略：买点需要成交量 > 近5日均量 × 1.5
            if vol_ratio < 1.5:
                continue

            label = _buy_type_from_point(bp)
            if label is None:
                continue
            sig = BottomFractalSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                fractal_index=fractal.index,
                fractal_timestamp=fractal.timestamp,
                fractal_price=fractal.price,
                fractal_high=fractal.high,
                fractal_low=fractal.low,
                third_high=fractal.third_high,
                stop_loss=fractal.third_low,
                buy_label=label,
                analysis_date=analysis_date,
            )
            signals.append(sig)

        elif _is_sell_point(bp):
            # 卖点信号只对持仓股有意义，非持仓跳过
            if not is_position:
                continue
            label = _sell_type_from_point(bp)
            if label is None:
                continue
            sig = TopFractalSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                fractal_index=fractal.index,
                fractal_timestamp=fractal.timestamp,
                fractal_price=fractal.price,
                fractal_high=fractal.high,
                fractal_low=fractal.low,
                third_low=fractal.third_low,
                stop_loss=fractal.high,
                sell_label=label,
                analysis_date=analysis_date,
            )
            signals.append(sig)

    return signals


# ============================================================
# 15分钟背驰段信号（持仓专用）
# ============================================================

def check_divergence_zone(
    core_15min: ChanlunCore,
) -> tuple:
    """
    检查15分钟级别是否在背驰段

    返回: (in_zone, zs_high, zs_low, prev_area)

    判断逻辑（完全分类）：
      - 有2个下跌中枢 → 看第二个中枢的离开笔
      - 离开笔的MACD面积 < 前一段离开笔 → 背驰段
      - 否则 → 不在背驰段
    """
    # 找下跌中枢
    down_zs = [zs for zs in core_15min.zhong_shus
               if zs.direction == Direction.DOWN]

    if len(down_zs) < 2:
        return False, None, None, None

    # 取第二个中枢
    zs = down_zs[-1]

    # 找中枢后的向下离开笔
    exit_bis = [
        b for i, b in enumerate(core_15min.bis)
        if b.direction == Direction.DOWN and i >= zs.end_bi_index
    ]
    if not exit_bis:
        return False, None, None, None

    # 找前一段离开笔
    prev_exit_bis = [
        b for i, b in enumerate(core_15min.bis)
        if b.direction == Direction.DOWN and i < zs.end_bi_index
        and i >= zs.start_bi_index - 2
    ]
    if len(prev_exit_bis) < 1:
        return False, None, None, None

    prev_exit = prev_exit_bis[-1]
    curr_exit = exit_bis[-1]

    # 计算MACD面积
    prev_area = core_15min._bi_macd_area(prev_exit)
    curr_area = core_15min._bi_macd_area(curr_exit)

    # 背驰判断：当前离开笔 MACD 面积 < 前一段的 85%
    in_zone = (prev_area > 0 and curr_area < prev_area * 0.85)

    return in_zone, zs.high, zs.low, prev_area


# ============================================================
# 主流程
# ============================================================

def run_static_analysis(
    state_store: StateStore,
    analysis_date: Optional[str] = None,
    use_watchlist: bool = False,
) -> List[object]:
    """
    运行完整静态分析，生成所有信号模板

    Args:
        state_store: StateStore 实例
        analysis_date: 分析日期（默认今天）
        use_watchlist: True=仅分析自选股+持仓, False=全市场A股

    Returns:
        所有生成的信号模板列表
    """
    if analysis_date is None:
        analysis_date = datetime.now(_CST).strftime("%Y-%m-%d")

    logger.info(f"=== 开始静态分析: {analysis_date} ===")

    # 1. 加载数据源
    positions = load_positions()
    position_codes = {p.get("股票代码", "") for p in positions}
    logger.info(f"持仓: {len(positions)} 只")

    if use_watchlist:
        # 旧模式：仅分析自选股+持仓
        watchlist = load_watchlist()
        logger.info(f"自选股: {len(watchlist)} 只")
        watchlist_codes = set()
        for w in watchlist:
            code = w.get("code", "") if isinstance(w, dict) else str(w)
            if code and not code.startswith("399") and not code.startswith("880"):
                watchlist_codes.add(code)
        all_codes = sorted(position_codes | watchlist_codes)
    else:
        # 新模式：从 QMT 获取全市场 A 股代码（排除科创板688和北交所8xx/920/BJ）
        logger.info("正在从 QMT 获取全市场股票列表...")
        market_codes = get_full_market_codes()
        # 确保持仓也在分析列表中
        all_codes = sorted(set(market_codes) | position_codes)
        logger.info(f"待分析: {len(all_codes)} 只 ({len(market_codes)} 全市场)")

    all_signals = []
    fetcher = RealtimeFetcher()
    total = len(all_codes)

    # 批量获取基本面数据（PE），用于过滤亏损股
    logger.info("正在批量获取基本面数据（PE）...")
    fin_info = fetch_financial_info(all_codes)
    filtered = [code for code, info in fin_info.items()
                if should_filter_stock(info)]
    if filtered:
        logger.info(f"亏损股 {len(filtered)} 只将被过滤（亏损且无改善迹象）")

    for idx, code in enumerate(all_codes):
        stock_name = ""
        # 持仓股票的名称从持仓文件获取
        for p in positions:
            if p.get("股票代码") == code:
                stock_name = p.get("名称", code)
                break
        if not stock_name:
            stock_name = code

        # 每 500 只打一次进度
        if (idx + 1) % 500 == 0 or idx == 0:
            logger.info(f"进度: {idx+1}/{total} ({100*(idx+1)//total}%)")

        # 过滤亏损股（PE<0且亏损无改善迹象的跳过，持仓股不过滤）
        if code not in position_codes:
            info = fin_info.get(code, {})
            if should_filter_stock(info):
                name = info.get("name", code)
                pe = info.get("pe", "?")
                logger.debug(f"{code} {name} PE={pe} 亏损无改善，跳过")
                continue

        # 3. 日线分析
        daily_df = load_kline_data(code, days=365, scale=240)
        if daily_df is None or len(daily_df) < 60:
            logger.debug(f"{code} 日线数据不足，跳过")
            continue

        core = ChanlunCore()
        core.process_klines(daily_df[["open", "high", "low", "close"]])
        core.find_fractals()
        core.find_bis()
        core.find_zhong_shus()
        if len(daily_df) > 30:
            core._calc_macd(daily_df["close"].astype(float))
        core.find_buy_sell_points()

        logger.debug(f"{code} {stock_name}: "
                     f"分型={len(core.fractals)} 笔={len(core.bis)} "
                     f"中枢={len(core.zhong_shus)} 买卖点={len(core.buy_sell_points)}")

        # 4. 生成日线信号模板
        is_pos = code in position_codes
        daily_signals = generate_daily_signals(code, stock_name, core, daily_df, analysis_date, is_position=is_pos)
        all_signals.extend(daily_signals)

        # 5. 持仓 → 15分钟背驰段检查
        if code in position_codes:
            min15_df = load_kline_data(code, days=60, scale=15)
            if min15_df is not None and len(min15_df) >= 60:
                core_15 = ChanlunCore()
                core_15.process_klines(min15_df[["open", "high", "low", "close"]])
                core_15.find_fractals()
                core_15.find_bis()
                core_15.find_zhong_shus()
                if len(min15_df) > 30:
                    core_15._calc_macd(min15_df["close"].astype(float))

                in_zone, zs_high, zs_low, prev_area = check_divergence_zone(core_15)

                div_signal = DivergenceZoneSignal(
                    stock_code=code,
                    stock_name=stock_name,
                    div_status=DivergenceStatus.IN_ZONE if in_zone else DivergenceStatus.NOT_IN_ZONE,
                    zhongshu_high=zs_high,
                    zhongshu_low=zs_low,
                    prev_exit_bi_macd_area=prev_area,
                )
                all_signals.append(div_signal)

                if in_zone:
                    logger.info(f"  ⚠ {stock_name} 15分钟在背驰段")

    # 6. 生成持仓风控信号
    for p in positions:
        code = p.get("股票代码", "")
        name = p.get("名称", code)
        cost = float(p.get("成本价", 0))
        shares = int(p.get("持有数量", 0))

        # 风控阈值：优先使用持仓文件中手动设置的止损价
        buy_reason = p.get("买入依据", {})
        manual_stop = 0
        if isinstance(buy_reason, dict):
            ms = buy_reason.get("止损价", 0)
            if ms is not None and ms != "":
                try:
                    manual_stop = float(ms)
                except (ValueError, TypeError):
                    manual_stop = 0
        stop_loss = float(manual_stop) if manual_stop > 0 else (round(cost * 0.95, 2) if cost else 0)
        profit_30 = round(cost * 1.30, 2) if cost else 0
        alert_up = round(cost * 1.03, 2) if cost else 0
        alert_down = round(cost * 0.97, 2) if cost else 0

        risk_signal = PositionRiskSignal(
            stock_code=code,
            stock_name=name,
            cost_price=cost,
            position_shares=shares,
            position_value=cost * shares,
            stop_loss_price=stop_loss,
            profit_30pct_price=profit_30,
            alert_3pct_up=alert_up,
            alert_3pct_down=alert_down,
        )
        all_signals.append(risk_signal)

    # 7. 写入 DB（保留历史信号，只清除pending状态的旧信号）
    logger.info(f"生成信号模板 {len(all_signals)} 条，写入 DB")
    state_store.clear_signal_templates(keep_history=True)
    state_store.save_signal_templates(all_signals)
    logger.info("=== 静态分析完成 ===")

    return all_signals


# ============================================================
# 独立入口
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="盘后静态分析")
    parser.add_argument("--watchlist", action="store_true",
                        help="仅分析自选股+持仓（默认全市场）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    store = StateStore()
    if args.watchlist:
        # 调用旧逻辑：自选股+持仓（通过参数控制）
        run_static_analysis(store, use_watchlist=True)
    else:
        run_static_analysis(store)
