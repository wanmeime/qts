# -*- coding: utf-8 -*-
"""
QMT 行情转发服务（Windows端）
================================

通过 Flask 将 QMT xtquant 的实时行情、K线、持仓数据以 HTTP 方式暴露，
供 WSL Linux 端（watchdog / dashboard）调用。

启动方式（Windows cmd, 以管理员身份运行）:
    cd /d D:\国金QMT交易端模拟\bin.x64
    python D:\qmt_bridge\qmt_bridge.py

注意：启动前必须先打开 MiniQMT 并登录。
"""

import sys
import json
import time
import logging
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

from xtquant.xtdata import (
    get_full_tick,
    get_market_data_ex,
    get_instrument_detail,
    get_sector_list,
    get_stock_list_in_sector,
)

# ── 交易模块（模拟盘） ──
_XTTRADE_AVAILABLE = False
try:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xtconstant import STOCK_BUY, STOCK_SELL, FIX_PRICE
    _XTTRADE_AVAILABLE = True
except ImportError:
    print("[qmt_bridge] xttrader 模块不可用，交易接口将返回错误")
    XtQuantTrader = None
    STOCK_BUY = STOCK_SELL = FIX_PRICE = None

# 全局交易对象和账户ID
_xt_trader = None
_xt_account_id = "88032229"  # MiniQMT 登录账户

# 股票名称缓存
_name_cache = {}


def _get_stock_name(code: str) -> str:
    """获取股票中文名称（带缓存）"""
    if code in _name_cache:
        return _name_cache[code]
    try:
        detail = get_instrument_detail(code)
        if detail:
            name = detail.get("InstrumentName", "") or detail.get("InstrumentName", "")
            if name:
                _name_cache[code] = name
                return name
    except Exception:
        pass
    # 从代码反推简称
    _name_cache[code] = code.replace(".SH", "").replace(".SZ", "")
    return _name_cache[code]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qmt_bridge")

app = Flask(__name__)
CORS(app)


# ============================================================
# 工具函数
# ============================================================

def _format_tick(data: dict) -> dict:
    """标准化 tick 数据字段"""
    lc = data.get("lastClose", 0) or data.get("open", 0)
    price = data.get("lastPrice", 0)
    return {
        "code": "",
        "price": price,
        "open": data.get("open", 0),
        "high": data.get("high", 0),
        "low": data.get("low", 0),
        "volume": data.get("volume", 0),
        "amount": data.get("amount", 0),
        "lastClose": lc,
        "change": round(price - lc, 4),
        "change_pct": round((price - lc) / lc * 100, 4) if lc else 0,
    }


def _ensure_qmt_code(code: str) -> str:
    """将裸代码转为 QMT 格式（300450 → 300450.SZ）"""
    if "." in code:
        return code
    if code.startswith("6") or code.startswith("9"):
        return f"{code}.SH"
    return f"{code}.SZ"


# ============================================================
# REST API
# ============================================================

@app.route("/api/status")
def api_status():
    """服务状态"""
    # 快速验证 QMT 连接
    try:
        tick = get_full_tick(["000001.SZ"])
        qmt_ok = len(tick) > 0
    except Exception:
        qmt_ok = False
    return jsonify({
        "status": "running" if qmt_ok else "qmt_disconnected",
        "qmt_connected": qmt_ok,
        "time": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/quotes")
def api_quotes():
    """获取实时行情（从缓存，如无可用的缓存则返回空）"""
    return jsonify({"note": "请使用 /api/quotes/batch 接口按需获取"})


@app.route("/api/quotes/batch")
def api_quotes_batch():
    """直接从 QMT 获取实时行情"""
    codes_str = request.args.get("codes", "")
    if not codes_str:
        return jsonify({"error": "缺少 codes 参数"}), 400

    code_list = [_ensure_qmt_code(c.strip()) for c in codes_str.split(",") if c.strip()]
    if not code_list:
        return jsonify({})

    try:
        tick = get_full_tick(code_list)
        result = {}
        for code, data in tick.items():
            item = _format_tick(data)
            item["code"] = code
            item["name"] = _get_stock_name(code)
            result[code] = item
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/kline")
def api_kline():
    """获取历史K线数据"""
    code = request.args.get("code", "")
    period = request.args.get("period", "1d")
    count = int(request.args.get("count", 120))

    if not code:
        return jsonify({"error": "缺少 code 参数"}), 400

    qmt_code = _ensure_qmt_code(code)

    try:
        print(f"[kline] 请求: {code} period={period} count={count} qmt_code={qmt_code}")
        
        from xtquant.xtdata import get_market_data, download_history_data
        
        # 先下载历史数据
        print(f"[kline] 下载历史数据...")
        download_history_data(stock_code=qmt_code, period=period)
        
        # 获取K线数据
        print(f"[kline] 调用 get_market_data...")
        data = get_market_data(
            field_list=[],
            stock_list=[qmt_code],
            period=period,
            count=count,
            dividend_type='front',
        )
        print(f"[kline] get_market_data 返回 keys={list(data.keys()) if data else 'None'}")
        
        # get_market_data返回格式: {field_name: DataFrame(index=stock_code)}
        # 需要转换为按时间索引的格式
        if 'close' in data and hasattr(data['close'], 'empty') and not data['close'].empty:
            # 获取时间索引
            time_df = data.get('time')
            if time_df is not None and not time_df.empty:
                times = time_df.columns.tolist()
                records = []
                for t in times:
                    row = {
                        'time': str(t),
                        'open': round(float(data['open'][t].iloc[0]), 4) if t in data['open'].columns else 0,
                        'high': round(float(data['high'][t].iloc[0]), 4) if t in data['high'].columns else 0,
                        'low': round(float(data['low'][t].iloc[0]), 4) if t in data['low'].columns else 0,
                        'close': round(float(data['close'][t].iloc[0]), 4) if t in data['close'].columns else 0,
                        'volume': int(data['volume'][t].iloc[0]) if t in data['volume'].columns else 0,
                        'amount': round(float(data['amount'][t].iloc[0]), 4) if t in data['amount'].columns else 0,
                    }
                    records.append(row)
                print(f"[kline] 返回 {qmt_code}: {len(records)}条")
                return jsonify({"code": qmt_code, "period": period, "count": len(records), "data": records})
        
        print(f"[kline] 无数据")
        return jsonify({"code": qmt_code, "count": 0, "data": [], "period": period}), 200
    except Exception as e:
        print(f"[kline] 异常: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/kline_test")
def api_kline_test():
    """诊断K线接口，测试xtquant是否可用"""
    import sys as _sys
    results = {}
    
    try:
        import xtquant.xtdata as _xtd
        funcs = [f for f in dir(_xtd) if not f.startswith('_')]
        results['xtdata_funcs'] = funcs
    except Exception as e:
        results['import_error'] = str(e)
        return jsonify(results)
    
    # 2. 测试 get_market_data_ex - 不同参数组合
    for code, period in [('000001.SZ', '1d'), ('000001', '1d'), ('000001.SZ', 'day')]:
        try:
            data = get_market_data_ex(
                field_list=[],
                stock_list=[code],
                period=period,
                count=5,
                dividend_type='front',
            )
            stock_key = code if code in data else (list(data.keys())[0] if data else 'NO_KEY')
            df = data.get(stock_key)
            if df is not None and len(df) > 0:
                results[f'ex({code},{period})'] = f'{len(df)}条 cols={list(df.columns)} idx={str(df.index[0])[:20]}...'
            else:
                results[f'ex({code},{period})'] = f'空 df={df is not None} len={len(df) if df is not None else 0}'
        except Exception as e:
            results[f'ex({code},{period})'] = f'错误: {str(e)[:60]}'
    
    # 3. 直接测试get_market_data(不带_ex)
    try:
        from xtquant.xtdata import get_market_data
        for code in ['000001.SZ', '000001']:
            try:
                data2 = get_market_data(
                    field_list=[], stock_list=[code],
                    period='1d', count=5, dividend_type='front',
                )
                sk = code if code in data2 else (list(data2.keys())[0] if data2 else None)
                if sk and sk in data2 and len(data2[sk]) > 0:
                    results[f'plain({code})'] = f'{len(data2[sk])}条'
                else:
                    results[f'plain({code})'] = '空'
            except Exception as e2:
                results[f'plain({code})'] = str(e2)[:60]
    except ImportError:
        results['plain'] = 'get_market_data 不存在'
    
    # 4. 检查数据目录
    import os as _os
    for p in [_os.path.expanduser('~/.xtquant'), 
              _os.path.expanduser('~/.quad_quant'), 
              'D:/国金QMT交易端模拟/bin.x64/xtdata']:
        if _os.path.exists(p):
            results[f'dir_{p}'] = _os.listdir(p)[:10]
        else:
            results[f'dir_{p}'] = '不存在'
    
    return jsonify(results)


@app.route("/api/instrument")
def api_instrument():
    """获取合约详情"""
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": "缺少 code 参数"}), 400
    qmt_code = _ensure_qmt_code(code)
    try:
        detail = get_instrument_detail(qmt_code)
        return jsonify({"code": qmt_code, "detail": detail})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 交易接口 — 模拟盘自动交易
# ============================================================


def _init_trade() -> bool:
    """初始化交易模块，连接 MiniQMT 模拟盘"""
    global _xt_trader, _xt_account_id
    if not _XTTRADE_AVAILABLE:
        logger.error("xttrader 模块不可用，交易功能禁用")
        return False
    try:
        # MiniQMT 用户数据路径
        mini_qmt_path = r"D:\国金QMT交易端模拟\userdata_mini"
        session_id = 1
        _xt_trader = XtQuantTrader(mini_qmt_path, session_id)
        _xt_trader.start()
        _xt_trader.connect()
        logger.info(f"交易模块初始化成功（账户={_xt_account_id}，路径={mini_qmt_path}）")
        return True
    except Exception as e:
        logger.error(f"交易模块初始化失败: {e}")
        _xt_trader = None
        return False


def _check_trade_ready() -> bool:
    """检查交易模块是否就绪"""
    return _xt_trader is not None


def _order_buy(qmt_code: str, price: float, volume: int, strategy: str = "") -> dict:
    """执行模拟买入"""
    try:
        order_id = _xt_trader.order_stock(
            account=_xt_account_id or "",
            stock_code=qmt_code,
            order_type=STOCK_BUY,
            order_volume=volume,
            price_type=FIX_PRICE,
            price=price,
            strategy_name=strategy,
        )
        return {"success": True, "order_id": str(order_id) if order_id else ""}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _order_sell(qmt_code: str, price: float, volume: int) -> dict:
    """执行模拟卖出"""
    try:
        order_id = _xt_trader.order_stock(
            account=_xt_account_id or "",
            stock_code=qmt_code,
            order_type=STOCK_SELL,
            order_volume=volume,
            price_type=FIX_PRICE,
            price=price,
            strategy_name="signal_auto",
        )
        return {"success": True, "order_id": str(order_id) if order_id else ""}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.route("/api/trade/buy", methods=["POST"])
def api_trade_buy():
    """模拟盘买入"""
    if not _check_trade_ready():
        return jsonify({"success": False, "error": "交易模块未就绪"}), 503

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体为空"}), 400

    code = data.get("code", "")
    price = data.get("price", 0)
    volume = data.get("volume", 0)

    if not code or price <= 0 or volume <= 0:
        return jsonify({"success": False, "error": f"参数不完整: code={code} price={price} volume={volume}"}), 400

    qmt_code = _ensure_qmt_code(code)
    strategy = data.get("strategy", "")

    # 价格偏离市价超 5% 拒绝
    try:
        tick = get_full_tick([qmt_code])
        if qmt_code in tick:
            mp = tick[qmt_code].get("lastPrice", 0)
            if mp > 0:
                deviation = abs(price - mp) / mp * 100
                if deviation > 5.0:
                    return jsonify({"success": False, "error": f"价格偏离市价 {deviation:.1f}%", "market_price": mp}), 400
    except Exception:
        pass

    result = _order_buy(qmt_code, price, volume, strategy)
    if result["success"]:
        logger.info(f"买入: {qmt_code} {volume}股 @ {price}（{strategy}）→ id={result['order_id']}")
    else:
        logger.error(f"买入失败: {qmt_code} → {result['error']}")

    return jsonify({"success": result["success"], "order_id": result.get("order_id", ""), "msg": "委托已提交" if result["success"] else result["error"]})


@app.route("/api/trade/sell", methods=["POST"])
def api_trade_sell():
    """模拟盘卖出"""
    if not _check_trade_ready():
        return jsonify({"success": False, "error": "交易模块未就绪"}), 503

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体为空"}), 400

    code = data.get("code", "")
    price = data.get("price", 0)
    volume = data.get("volume", 0)

    if not code or price <= 0 or volume <= 0:
        return jsonify({"success": False, "error": "参数不完整"}), 400

    qmt_code = _ensure_qmt_code(code)
    result = _order_sell(qmt_code, price, volume)
    if result["success"]:
        logger.info(f"卖出: {qmt_code} {volume}股 @ {price} → id={result['order_id']}")
    else:
        logger.error(f"卖出失败: {qmt_code} → {result['error']}")

    return jsonify({"success": result["success"], "order_id": result.get("order_id", ""), "msg": "委托已提交" if result["success"] else result["error"]})


@app.route("/api/trade/positions")
def api_trade_positions():
    """查询模拟持仓"""
    if not _check_trade_ready():
        return jsonify({"success": False, "error": "交易模块未就绪"}), 503
    try:
        positions = _xt_trader.query_stock_positions(_xt_account_id or "")
        result = []
        for pos in positions:
            result.append({
                "code": pos.get("stock_code", ""),
                "name": _get_stock_name(pos.get("stock_code", "")),
                "volume": pos.get("volume", 0),
                "available": pos.get("available_volume", 0),
                "cost": pos.get("open_price", 0),
                "current": pos.get("last_price", 0),
                "pnl": pos.get("pnl_ratio", 0),
            })
        return jsonify({"success": True, "count": len(result), "positions": result})
    except Exception as e:
        logger.error(f"查询持仓失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/trade/asset")
def api_trade_asset():
    """查询账户资产"""
    if not _check_trade_ready():
        return jsonify({"success": False, "error": "交易模块未就绪"}), 503
    try:
        asset = _xt_trader.query_stock_asset(_xt_account_id or "")
        return jsonify({"success": True, "asset": asset})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/trade/orders")
def api_trade_orders():
    """查询当日委托"""
    if not _check_trade_ready():
        return jsonify({"success": False, "error": "交易模块未就绪"}), 503
    try:
        orders = _xt_trader.query_stock_orders(_xt_account_id or "")
        result = []
        for o in orders:
            result.append({
                "order_id": o.get("order_id", ""),
                "code": o.get("stock_code", ""),
                "direction": "buy" if o.get("order_type") == STOCK_BUY else "sell",
                "price": o.get("price", 0),
                "volume": o.get("order_volume", 0),
                "filled": o.get("filled_volume", 0),
                "status": o.get("order_status", ""),
            })
        return jsonify({"success": True, "count": len(result), "orders": result})
    except Exception as e:
        logger.error(f"查询委托失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QMT 行情转发服务")
    parser.add_argument("--port", type=int, default=8890, help="监听端口")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--simulate", action="store_true", default=True, help="模拟盘模式")
    args = parser.parse_args()

    # 初始化交易模块
    if args.simulate:
        _init_trade()

    logger.info(f"QMT 行情转发服务启动 → http://{args.host}:{args.port}")
    if _xt_trader:
        logger.info("交易接口: 已启用（模拟盘）")
    else:
        logger.info("交易接口: 未就绪（仅行情模式）")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
