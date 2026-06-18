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
        print(f"[kline] 请求: {code} period={period} count={count}")
        
        # 用 get_market_data_ex 获取前复权K线
        data = get_market_data_ex(
            field_list=[],
            stock_list=[qmt_code],
            period=period,
            count=count,
            dividend_type="front",
        )
        
        if qmt_code in data and len(data[qmt_code]) > 0:
            df = data[qmt_code]
            records = []
            for idx in range(len(df)):
                row = {}
                for col in df.columns:
                    val = df[col].iloc[idx]
                    if isinstance(val, (float, int)):
                        row[col] = int(val) if col in ('volume','amount') else round(float(val), 4)
                    else:
                        row[col] = str(val)
                row['time'] = str(df.index[idx])
                records.append(row)
            print(f"[kline] 返回 {qmt_code}: {len(records)}条")
            return jsonify({"code": qmt_code, "period": period, "count": len(records), "data": records})
        else:
            print(f"[kline] get_market_data_ex 为空, 尝试 get_market_data...")
            try:
                from xtquant.xtdata import get_market_data
                data2 = get_market_data(
                    field_list=[],
                    stock_list=[qmt_code],
                    period=period,
                    count=count,
                    dividend_type='front',
                )
                if qmt_code in data2 and len(data2[qmt_code]) > 0:
                    df2 = data2[qmt_code]
                    records2 = []
                    for idx in range(len(df2)):
                        row2 = {}
                        for col in df2.columns:
                            val = df2[col].iloc[idx]
                            row2[col] = int(val) if col in ('volume','amount') else round(float(val), 4)
                        row2['time'] = str(df2.index[idx])
                        records2.append(row2)
                    print(f"[kline] get_market_data 返回 {len(records2)}条")
                    return jsonify({"code": qmt_code, "period": period, "count": len(records2), "data": records2})
            except Exception as e2:
                print(f"[kline] get_market_data 失败: {e2}")
            
            return jsonify({"code": qmt_code, "count": 0, "data": [], "period": period}), 200
    except Exception as e:
        print(f"[kline] 异常: {e}")
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
# 主入口
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QMT 行情转发服务")
    parser.add_argument("--port", type=int, default=8890, help="监听端口")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    logger.info(f"QMT 行情转发服务启动 → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
