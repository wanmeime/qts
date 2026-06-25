# 收盘后静态分析 + HTML报告生成脚本
# 供 cron job 调用

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

_CST = timezone(timedelta(hours=8))

# 路径
PROJECT_ROOT = Path("/home/jiaod/qts")
sys.path.insert(0, str(PROJECT_ROOT / "10-策略" / "缠论Agent"))
sys.path.insert(0, str(PROJECT_ROOT / "50-盯盘"))

from state_store import StateStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eod_report")

def generate_html_report(analysis_time: str, signals: List[Dict], scan_count: int) -> str:
    """生成收盘扫描 HTML 报告"""
    pending_signals = [s for s in signals if s.get("status") == "pending"]
    activated_signals = [s for s in signals if s.get("status") == "activated"]

    def render_signal(s):
        data = s.get("data", {})
        code = data.get("stock_code", s.get("stock_code", ""))
        name = data.get("stock_name", code)
        stype = s.get("signal_type", "")
        status = s.get("status", "")
        label = data.get("buy_label", stype)
        fractal_price = data.get("fractal_price", "")
        third_high = data.get("third_high", "")
        stop_loss = data.get("stop_loss", "")
        if label == "buy1":
            label_cn = "一买"
        elif label == "buy2":
            label_cn = "二买"
        elif label == "buy3":
            label_cn = "三买"
        elif label == "secondary_buy":
            label_cn = "类二买"
        else:
            label_cn = label
        if status == "pending":
            status_cn = "⚪ 待突破"
        elif status == "activated":
            status_cn = "🟢 已突破"
        elif status == "invalidated":
            status_cn = "🔴 已失效"
        else:
            status_cn = status
        return f"""
        <tr>
          <td class="center">{code}</td>
          <td>{name}</td>
          <td class="center">{label_cn}</td>
          <td class="right">{fractal_price}</td>
          <td class="right">{third_high}</td>
          <td class="right">{stop_loss}</td>
          <td class="center">{status_cn}</td>
        </tr>"""

    signals_html = ""
    if not pending_signals and not activated_signals:
        signals_html = '<tr><td colspan="7" class="center" style="color:#888;">今日无待突破信号</td></tr>'
    else:
        for s in pending_signals:
            signals_html += render_signal(s)
        for s in activated_signals:
            signals_html += render_signal(s)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QTS 收盘静态扫描报告</title>
<style>
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
  .container {{ max-width: 800px; margin: 0 auto; background: #fff; border-radius: 8px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ background: #f0f0f0; padding: 10px 8px; text-align: center; font-weight: 600; border-bottom: 2px solid #ddd; }}
  td {{ padding: 10px 8px; border-bottom: 1px solid #eee; }}
  td.right {{ text-align: right; font-family: "JetBrains Mono", monospace; }}
  td.center {{ text-align: center; }}
  tr:hover {{ background: #fafafa; }}
  .summary {{ background: #f8f9fa; padding: 12px; border-radius: 4px; margin-bottom: 16px; font-size: 13px; color: #444; }}
  .footer {{ margin-top: 16px; font-size: 12px; color: #999; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h1>📊 QTS 收盘静态扫描报告</h1>
  <div class="meta">生成时间: {analysis_time} | 扫描股票数: {scan_count} | 信号总数: {len(pending_signals) + len(activated_signals)}</div>
  <div class="summary">
    📌 <b>重点观察（pending）</b>: {len(pending_signals)} 只 — 明日盘中需实时监控突破<br>
    ✅ <b>已突破（activated）</b>: {len(activated_signals)} 只 — 今日盘中已触发买入确认
  </div>
  <table>
    <thead>
      <tr>
        <th>代码</th>
        <th>名称</th>
        <th>类型</th>
        <th>分型价</th>
        <th>突破位</th>
        <th>止损位</th>
        <th>状态</th>
      </tr>
    </thead>
    <tbody>{signals_html}</tbody>
  </table>
  <div class="footer">由 Wu's QTS 盯盘系统自动生成 | 次日盘中请运行 signal_monitor 加载信号</div>
</div>
</body>
</html>"""
    return html


def main():
    analysis_time = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
    store = StateStore()

    # 刷新 signals（static_analyzer 已经写库）
    signals = store.get_pending_signals()
    # 也读取 activated 的（当天盘中已触发）
    activated = store.load_signal_templates(status="activated")
    all_signals = signals + activated

    # 统计扫描股票数（自选股数量，可扩展）
    watchlist_path = PROJECT_ROOT / "00-研究" / "自选股" / "watchlist.json"
    scan_count = 0
    if watchlist_path.exists():
        try:
            with open(watchlist_path, "r", encoding="utf-8") as f:
                watchlist = json.load(f)
                scan_count = len(watchlist)
        except Exception:
            scan_count = 0

    # 生成 HTML
    html = generate_html_report(analysis_time, all_signals, scan_count)

    # 保存到 30-信号
    today_str = datetime.now(_CST).strftime("%Y%m%d")
    out_path = PROJECT_ROOT / "30-信号" / f"eod_report_{today_str}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML 报告已生成: {out_path}")
    print(f"报告路径: {out_path}")
    print(f"pending 信号数: {len(signals)}")
    print(f"activated 信号数: {len(activated)}")

    # 把信号摘要也打印出来，供发送
    print("\n=== 重点观察信号（次日需实时监控）===")
    for s in signals:
        data = s.get("data", {})
        print(f"  {data.get('stock_code','')} {data.get('stock_name','')} | {data.get('buy_label','')} | 分型={data.get('fractal_price','')} | 突破={data.get('third_high','')} | 止损={data.get('stop_loss','')}")


if __name__ == "__main__":
    main()
