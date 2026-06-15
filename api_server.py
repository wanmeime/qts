"""
QTS 数据API服务
================
提供REST API接口，任何系统通过HTTP调用即可获取数据。

启动：python3 api_server.py
端口：默认 8899

接口列表：
  GET /                        — 数据概览
  GET /market                  — 全市场行情
  GET /market/top-gainers      — 涨幅排行
  GET /market/top-losers       — 跌幅排行
  GET /kline/{symbol}          — 单只K线
  GET /kline/batch?symbols=xx,yy — 批量K线
  GET /macro/cpi               — CPI
  GET /macro/pmi               — PMI
  GET /macro/shibor            — Shibor
  GET /macro/gdp               — GDP
  GET /industry                — 行业板块
  GET /stock/{symbol}          — 个股信息
  GET /health                  — 健康检查
"""

import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 确保能导入 qts_data
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qts_data as qd
import pandas as pd

PORT = int(os.environ.get("QTS_PORT", 8899))


def df_to_json(df):
    """DataFrame 转 JSON 列表"""
    return df.to_dict(orient="records")


def df_to_csv(df):
    """DataFrame 转 CSV 字符串"""
    return df.to_csv(index=False)


class QTSHandler(BaseHTTPRequestHandler):

    def _send(self, code, data, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if isinstance(data, str):
            self.wfile.write(data.encode("utf-8"))
        else:
            self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _send_error(self, code, msg):
        self._send(code, {"error": msg})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # 输出格式：?format=csv 默认json
        fmt = params.get("format", ["json"])[0]

        try:
            # ==================== 路由 ====================

            if path == "" or path == "/":
                info = qd.data_info()
                self._send(200, {"status": "ok", "data": info})

            elif path == "/health":
                self._send(200, {"status": "ok", "service": "qts-data-api", "port": PORT})

            # ---------- 行情 ----------
            elif path == "/market":
                df = qd.market()
                if fmt == "csv":
                    self._send(200, df_to_csv(df), "text/csv")
                else:
                    self._send(200, {"count": len(df), "data": df_to_json(df)})

            elif path == "/market/top-gainers":
                n = int(params.get("n", [20])[0])
                df = qd.top_gainers(n)
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            elif path == "/market/top-losers":
                n = int(params.get("n", [20])[0])
                df = qd.top_losers(n)
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            # ---------- K线 ----------
            elif path.startswith("/kline/batch"):
                symbols_str = params.get("symbols", [""])[0]
                if not symbols_str:
                    self._send_error(400, "缺少 symbols 参数，用法: /kline/batch?symbols=sh600519,sz300750")
                    return
                symbols = [s.strip() for s in symbols_str.split(",")]
                limit = int(params.get("limit", [120])[0])
                result = {}
                for sym in symbols:
                    try:
                        df = qd.kline(sym).tail(limit)
                        result[sym] = df_to_json(df)
                    except FileNotFoundError:
                        result[sym] = None
                self._send(200, {"count": len(result), "data": result})

            elif path.startswith("/kline/"):
                symbol = path.split("/")[-1]
                limit = int(params.get("limit", [120])[0])
                df = qd.kline(symbol).tail(limit)
                if fmt == "csv":
                    self._send(200, df_to_csv(df), "text/csv")
                else:
                    self._send(200, {"symbol": symbol, "count": len(df), "data": df_to_json(df)})

            # ---------- 宏观 ----------
            elif path == "/macro/cpi":
                df = qd.cpi()
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            elif path == "/macro/pmi":
                df = qd.pmi()
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            elif path == "/macro/shibor":
                df = qd.shibor()
                limit = int(params.get("limit", [30])[0])
                df = df.tail(limit)
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            elif path == "/macro/gdp":
                df = qd.gdp()
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            # ---------- 行业 ----------
            elif path == "/industry":
                df = qd.industries()
                self._send(200, {"count": len(df), "data": df_to_json(df)})

            # ---------- 个股 ----------
            elif path.startswith("/stock/"):
                symbol = path.split("/")[-1]
                info = qd.stock_info(symbol)
                if info:
                    self._send(200, {"data": info})
                else:
                    self._send_error(404, f"未找到股票: {symbol}")

            # ---------- 404 ----------
            else:
                self._send_error(404, f"未知接口: {path}")

        except FileNotFoundError as e:
            self._send_error(404, str(e))
        except Exception as e:
            self._send_error(500, f"服务器错误: {str(e)}")

    def log_message(self, format, *args):
        # 简化日志
        print(f"[{self.log_date_time_string()}] {args[0]}")


def main():
    server = HTTPServer(("0.0.0.0", PORT), QTSHandler)
    print(f"=" * 50)
    print(f"  QTS 数据API服务")
    print(f"  地址: http://0.0.0.0:{PORT}")
    print(f"  文档: http://localhost:{PORT}/")
    print(f"=" * 50)
    print(f"\n可用接口:")
    print(f"  GET /                       数据概览")
    print(f"  GET /market                 全市场行情")
    print(f"  GET /market/top-gainers     涨幅排行 (?n=20)")
    print(f"  GET /market/top-losers      跌幅排行 (?n=20)")
    print(f"  GET /kline/{{symbol}}         单只K线 (?limit=120)")
    print(f"  GET /kline/batch?symbols=x,y 批量K线")
    print(f"  GET /macro/cpi              CPI数据")
    print(f"  GET /macro/pmi              PMI数据")
    print(f"  GET /macro/shibor           Shibor利率 (?limit=30)")
    print(f"  GET /macro/gdp              GDP数据")
    print(f"  GET /industry               行业板块")
    print(f"  GET /stock/{{symbol}}         个股信息")
    print(f"  GET /health                 健康检查")
    print(f"\n所有接口支持 ?format=csv 返回CSV格式")
    print(f"\n等待请求...\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
