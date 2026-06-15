#!/usr/bin/env python3
"""批量分析自选股 - 前30只A股 (v2)"""

import json
import csv
import time
import os
import re
import subprocess
import sys
from datetime import datetime

WATCHLIST_PATH = "/home/jiaod/qts/00-研究/自选股/watchlist.json"
API_URL = "http://localhost:8000/v1/analyze"
TRADE_DATE_FMT = "2026-06-07"
ANALYSTS = ["market", "macro", "news", "smart_money"]
CSV_OUTPUT = "/home/jiaod/qts/30-信号/自选股分析_20260607_v2.csv"
MD_OUTPUT = "/home/jiaod/qts/30-信号/自选股分析摘要_20260607_v2.md"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4Y2Y0MTZmYi1hYjM1LTRkOTUtOTcxZC1hODVhY2Y1ZDY0ZDgiLCJlbWFpbCI6ImFkbWluQHF0cy5sb2NhbCIsImV4cCI6MTc4MzQyMjg2NiwiaWF0IjoxNzgwODMwODY2fQ.vMKWJ6EwBSDpVEDMz9998oSlPjC3fVjvMJ70-ALMQcc"
MAX_STOCKS = 30
MAX_WAIT = 600  # 10 min per stock
POLL_INTERVAL = 8


def load_watchlist():
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def is_a_share(item):
    """Check if it's an A-share stock (not US stock, not index)"""
    market = item.get("market", "")
    code = item.get("code", "")
    if "美股" in market:
        return False
    if code.startswith("399"):
        return False  # Index codes like 399001, 399006
    return "A股" in market or "创业板" in market


def get_symbol(code, market):
    """Convert code to API symbol format (e.g., 600519.SH)"""
    if code.startswith("6") or code.startswith("68"):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"


def curl_json(method, url, data=None):
    """Make HTTP request using curl and return parsed JSON."""
    cmd = ["curl", "-s", "-X", method, url,
           "-H", f"Authorization: Bearer {TOKEN}",
           "--max-time", "60"]
    if method == "POST" and data:
        cmd.extend(["-H", "Content-Type: application/json",
                     "-d", json.dumps(data, ensure_ascii=False)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"    curl error: {e}")
    return None


def poll_job(job_id):
    """Poll job until completion or timeout."""
    start = time.time()
    while time.time() - start < MAX_WAIT:
        resp = curl_json("GET", f"http://localhost:8000/v1/jobs/{job_id}")
        if resp:
            status = resp.get("status")
            if status == "completed":
                result = curl_json("GET", f"http://localhost:8000/v1/jobs/{job_id}/result")
                if result:
                    result["status"] = "completed"
                    return result
                return resp
            elif status == "failed":
                resp["status"] = "failed"
                return resp
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout"}


def extract_decision(response):
    """Extract buy/sell/hold decision from API response."""
    if not response:
        return "ERROR", "分析失败", ""

    status = response.get("status", "")
    if status in ("failed", "timeout"):
        error_msg = response.get("error", response.get("detail", "未知错误"))
        return "ERROR", str(error_msg)[:200], ""

    try:
        # Check final_trade_decision first
        if "final_trade_decision" in response:
            ftd = response["final_trade_decision"]
            if isinstance(ftd, dict):
                decision = ftd.get("decision", "UNKNOWN")
                rationale = ftd.get("rationale", "")
                return str(decision).upper(), str(rationale)[:300], str(rationale)

        # Check various report keys for VERDICT
        reports = {}
        for key in response:
            if "report" in key.lower() and isinstance(response[key], str):
                reports[key] = response[key]

        # Try to extract VERDICT from reports
        for report_name, content in reports.items():
            if not content:
                continue
            # Look for VERDICT pattern
            verdict_match = re.search(r'VERDICT[:\s]*(\{[^}]+\})', content)
            if verdict_match:
                try:
                    verdict_str = verdict_match.group(1)
                    verdict = json.loads(verdict_str)
                    direction = verdict.get("direction", "")
                    if "偏多" in direction or "买入" in direction:
                        return "BUY", f"{report_name}: {direction}", content[:300]
                    elif "偏空" in direction or "卖出" in direction:
                        return "SELL", f"{report_name}: {direction}", content[:300]
                    elif "中性" in direction or "持有" in direction:
                        return "HOLD", f"{report_name}: {direction}", content[:300]
                except json.JSONDecodeError:
                    pass

            # Look for action/recommendation keywords
            if "买入" in content or "做多" in content:
                return "BUY", content[:300], content[:300]
            elif "卖出" in content or "做空" in content:
                return "SELL", content[:300], content[:300]
            elif "持有" in content or "观望" in content:
                return "HOLD", content[:300], content[:300]

        # Check content field
        if "content" in response and isinstance(response["content"], str):
            content = response["content"]
            if "买入" in content:
                return "BUY", content[:300], content[:300]
            elif "卖出" in content:
                return "SELL", content[:300], content[:300]
            elif "持有" in content:
                return "HOLD", content[:300], content[:300]
            return "ANALYZED", content[:300], content[:300]

        return "ANALYZED", json.dumps(response, ensure_ascii=False)[:300], json.dumps(response, ensure_ascii=False)[:300]

    except Exception as e:
        return "ERROR", f"解析错误: {e}", ""

    return "ERROR", "无法解析响应", ""


def main():
    print("=" * 60)
    print("自选股分析 v2 - 前30只A股")
    print("=" * 60)

    # Load and filter
    watchlist = load_watchlist()
    a_shares = [item for item in watchlist if is_a_share(item)]
    print(f"总自选股: {len(watchlist)}")
    print(f"A股股票: {len(a_shares)}")
    targets = a_shares[:MAX_STOCKS]
    print(f"本次分析: {len(targets)} 只")
    print()

    for i, s in enumerate(targets):
        symbol = get_symbol(s['code'], s['market'])
        print(f"  {i+1}. {s['code']} -> {symbol} ({s['market']}) - 价格: {s.get('price', 'N/A')}")

    # Ensure output directory
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)

    # Analyze
    results = []
    success_count = 0
    failed_count = 0

    for i, stock in enumerate(targets):
        code = stock["code"]
        symbol = get_symbol(code, stock["market"])
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(targets)}] 分析 {symbol} ({stock['market']})...")
        print(f"{'='*50}")

        start_time = time.time()
        payload = {
            "symbol": symbol,
            "trade_date": TRADE_DATE_FMT,
            "selected_analysts": ANALYSTS
        }
        resp = curl_json("POST", API_URL, payload)

        if not resp or "job_id" not in resp:
            elapsed = time.time() - start_time
            print(f"  提交失败: {resp}")
            results.append({
                "序号": i + 1, "代码": code, "symbol": symbol,
                "市场": stock["market"], "价格": stock.get("price", ""),
                "建议": "ERROR", "摘要": "API提交失败", "状态": "失败",
                "耗时(s)": f"{elapsed:.1f}"
            })
            failed_count += 1
            time.sleep(2)
            continue

        job_id = resp["job_id"]
        print(f"  任务ID: {job_id}")

        # Poll for completion
        job_result = poll_job(job_id)
        elapsed = time.time() - start_time

        if job_result and job_result.get("status") == "completed":
            decision, summary, detail = extract_decision(job_result)
            print(f"  结果: {decision}")
            print(f"  摘要: {summary[:100]}")
            print(f"  耗时: {elapsed:.1f}s")
            success_count += 1
            status = "成功"
        else:
            decision = "ERROR"
            error_msg = job_result.get("error", job_result.get("status", "未知")) if job_result else "无响应"
            summary = str(error_msg)[:200]
            detail = summary
            print(f"  失败! 状态: {job_result.get('status', 'unknown') if job_result else 'null'}")
            print(f"  错误: {summary[:100]}")
            print(f"  耗时: {elapsed:.1f}s")
            failed_count += 1
            status = "失败"

        results.append({
            "序号": i + 1, "代码": code, "symbol": symbol,
            "市场": stock["market"], "价格": stock.get("price", ""),
            "建议": decision, "摘要": summary, "状态": status,
            "耗时(s)": f"{elapsed:.1f}"
        })

        # Pause between requests
        if i < len(targets) - 1:
            time.sleep(2)

    # === Write CSV ===
    print(f"\n写入CSV: {CSV_OUTPUT}")
    with open(CSV_OUTPUT, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=["序号", "代码", "symbol", "市场", "价格", "建议", "摘要", "状态", "耗时(s)"])
        writer.writeheader()
        writer.writerows(results)

    # === Write MD ===
    print(f"写入MD: {MD_OUTPUT}")
    buy_list = [r for r in results if r["建议"] in ("BUY",)]
    sell_list = [r for r in results if r["建议"] in ("SELL",)]
    hold_list = [r for r in results if r["建议"] in ("HOLD",)]
    analyzed_list = [r for r in results if r["建议"] in ("ANALYZED",)]
    error_list = [r for r in results if r["建议"] in ("ERROR",)]

    with open(MD_OUTPUT, 'w', encoding='utf-8') as f:
        f.write(f"# 自选股分析摘要 - {TRADE_DATE_FMT}\n\n")
        f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 统计\n\n")
        f.write(f"- 总分析: {len(results)} 只\n")
        f.write(f"- 成功: {success_count} 只\n")
        f.write(f"- 失败: {failed_count} 只\n")
        f.write(f"- 买入建议: {len(buy_list)} 只\n")
        f.write(f"- 卖出建议: {len(sell_list)} 只\n")
        f.write(f"- 持有建议: {len(hold_list)} 只\n")
        f.write(f"- 已分析(无明确方向): {len(analyzed_list)} 只\n")
        f.write(f"- 错误: {len(error_list)} 只\n\n")

        f.write(f"## 分析结果\n\n")
        f.write(f"| 序号 | 代码 | Symbol | 市场 | 价格 | 建议 | 状态 | 耗时 |\n")
        f.write(f"|------|------|--------|------|------|------|------|------|\n")
        for r in results:
            f.write(f"| {r['序号']} | {r['代码']} | {r['symbol']} | {r['市场']} | {r['价格']} | {r['建议']} | {r['状态']} | {r['耗时(s)']}s |\n")

        if buy_list:
            f.write(f"\n## 推荐买入 ({len(buy_list)}只)\n\n")
            for r in buy_list:
                f.write(f"### {r['symbol']} ({r['市场']}) - 价格: {r['价格']}\n")
                f.write(f"{r['摘要']}\n\n")

        if sell_list:
            f.write(f"\n## 建议卖出 ({len(sell_list)}只)\n\n")
            for r in sell_list:
                f.write(f"### {r['symbol']} ({r['市场']}) - 价格: {r['价格']}\n")
                f.write(f"{r['摘要']}\n\n")

        if hold_list:
            f.write(f"\n## 建议持有 ({len(hold_list)}只)\n\n")
            for r in hold_list:
                f.write(f"### {r['symbol']} ({r['市场']}) - 价格: {r['价格']}\n")
                f.write(f"{r['摘要']}\n\n")

        if error_list:
            f.write(f"\n## 分析失败 ({len(error_list)}只)\n\n")
            for r in error_list:
                f.write(f"- {r['symbol']} ({r['市场']}): {r['摘要']}\n")

        # Top 5 recommendations
        positive = [r for r in results if r["建议"] in ("BUY", "HOLD") and r["状态"] == "成功"]
        if positive:
            f.write(f"\n## 前5名推荐\n\n")
            for r in positive[:5]:
                f.write(f"1. **{r['symbol']}** ({r['市场']}) - {r['建议']} - 价格: {r['价格']}\n")

    # Summary
    print(f"\n{'='*60}")
    print("分析完成!")
    print(f"{'='*60}")
    print(f"成功: {success_count}/{len(results)}")
    print(f"失败: {failed_count}/{len(results)}")

    if buy_list:
        print(f"\n买入建议:")
        for r in buy_list:
            print(f"  {r['symbol']} ({r['市场']}) - {r['摘要'][:80]}")
    if sell_list:
        print(f"\n卖出建议:")
        for r in sell_list:
            print(f"  {r['symbol']} ({r['市场']}) - {r['摘要'][:80]}")
    if hold_list:
        print(f"\n持有建议:")
        for r in hold_list:
            print(f"  {r['symbol']} ({r['市场']}) - {r['摘要'][:80]}")
    if error_list:
        print(f"\n失败:")
        for r in error_list:
            print(f"  {r['symbol']}: {r['摘要'][:80]}")

    return success_count, failed_count, results


if __name__ == "__main__":
    success, failed, results = main()
    sys.exit(0 if failed == 0 else 1)
