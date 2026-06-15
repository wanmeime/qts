#!/usr/bin/env python3
"""分批分析自选股 - 前20只A股股票"""

import json
import csv
import time
import subprocess
import sys
from datetime import datetime

WATCHLIST_PATH = "/home/jiaod/qts/00-研究/自选股/watchlist.json"
API_URL = "http://localhost:8000/v1/analyze"
TRADE_DATE = "20260607"
TRADE_DATE_FMT = "2026-06-07"
ANALYSTS = ["market", "macro", "news", "smart_money"]
CSV_OUTPUT = "/home/jiaod/qts/30-信号/自选股分析_20260607.csv"
MD_OUTPUT = "/home/jiaod/qts/30-信号/自选股分析摘要_20260607.md"
MAX_STOCKS = 20

def load_watchlist():
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def is_a_share(item):
    """Check if it's an A-share stock (not US stock, not index)"""
    market = item.get("market", "")
    code = item.get("code", "")
    # Filter: must be A-share market (深圳A股, 上海A股, 创业板)
    # Exclude: 美股, and index codes starting with 399
    if "美股" in market:
        return False
    if code.startswith("399"):
        return False  # Index codes like 399001, 399006
    return "A股" in market or "创业板" in market

def get_api_token():
    """获取API Token (使用测试账号)"""
    email = "test@example.com"

    # 1. 请求验证码
    resp = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://localhost:8000/v1/auth/request-code",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"email": email})],
        capture_output=True, text=True
    )
    data = json.loads(resp.stdout)
    code = data.get("dev_code")

    if not code:
        print("获取验证码失败")
        return None

    # 2. 验证验证码获取Token
    resp = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://localhost:8000/v1/auth/verify-code",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"email": email, "code": code})],
        capture_output=True, text=True
    )
    data = json.loads(resp.stdout)
    return data.get("access_token")


def check_job_status(job_id, token, max_wait=600):
    """检查任务状态并获取结果"""
    import time

    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            # 先检查状态
            result = subprocess.run(
                ["curl", "-s", f"http://localhost:8000/v1/jobs/{job_id}",
                 "-H", f"Authorization: Bearer {token}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                status = data.get("status")

                if status == "completed":
                    # 获取完整结果
                    result_resp = subprocess.run(
                        ["curl", "-s", f"http://localhost:8000/v1/jobs/{job_id}/result",
                         "-H", f"Authorization: Bearer {token}"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result_resp.returncode == 0 and result_resp.stdout.strip():
                        return json.loads(result_resp.stdout)
                    return data
                elif status == "failed":
                    return data

            time.sleep(5)
        except Exception as e:
            print(f"  检查任务状态出错: {e}")
            time.sleep(5)

    return {"status": "timeout"}


def call_api(symbol, retries=2):
    """Call TradingAgents API for analysis"""
    # 获取Token
    token = get_api_token()
    if not token:
        print("  获取Token失败")
        return None

    payload = json.dumps({
        "symbol": symbol,
        "trade_date": TRADE_DATE_FMT,
        "selected_analysts": ANALYSTS
    })

    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", API_URL,
                 "-H", "Content-Type: application/json",
                 "-H", f"Authorization: Bearer {token}",
                 "-d", payload,
                 "--max-time", "300"],  # 5 min timeout per stock
                capture_output=True,
                text=True,
                timeout=320
            )
            if result.returncode == 0 and result.stdout.strip():
                response = json.loads(result.stdout)
                # 如果返回job_id，等待任务完成
                if "job_id" in response:
                    job_id = response["job_id"]
                    print(f"  任务已提交: {job_id}，等待结果...")
                    job_result = check_job_status(job_id, token)
                    return job_result
                return response
            else:
                print(f"  [Attempt {attempt+1}] API error: {result.stderr or 'empty response'}")
        except json.JSONDecodeError as e:
            print(f"  [Attempt {attempt+1}] JSON parse error: {e}")
            print(f"  Raw response: {result.stdout[:500]}")
        except subprocess.TimeoutExpired:
            print(f"  [Attempt {attempt+1}] Timeout after 320s")
        except Exception as e:
            print(f"  [Attempt {attempt+1}] Error: {e}")

        if attempt < retries:
            time.sleep(5)

    return None

def extract_decision(response):
    """Extract buy/sell decision from API response"""
    if not response:
        return "ERROR", "分析失败"

    # Try to find decision in the response
    try:
        if isinstance(response, dict):
            # Look for common decision fields
            for key in ["decision", "signal", "recommendation", "action"]:
                if key in response:
                    return response[key].upper(), str(response[key])

            # Check nested structure
            if "final_trade_decision" in response:
                ftd = response["final_trade_decision"]
                if isinstance(ftd, dict):
                    decision = ftd.get("decision", ftd.get("signal", "UNKNOWN"))
                    rationale = ftd.get("rationale", ftd.get("reason", str(ftd)))
                    return str(decision).upper(), str(rationale)[:200]

            # Try to extract from content/analysis
            if "content" in response:
                content = response["content"]
                if isinstance(content, str):
                    content_lower = content.lower()
                    if "buy" in content_lower or "买入" in content:
                        return "BUY", content[:200]
                    elif "sell" in content_lower or "卖出" in content:
                        return "SELL", content[:200]
                    elif "hold" in content_lower or "持有" in content:
                        return "HOLD", content[:200]
                    return "ANALYZED", content[:200]

            # 从多个报告中提取方向
            reports = {
                "market_report": response.get("market_report", ""),
                "news_report": response.get("news_report", ""),
                "macro_report": response.get("macro_report", ""),
                "smart_money_report": response.get("smart_money_report", ""),
            }

            # 尝试从VERDICT注释中提取方向
            import re
            for report_name, report_content in reports.items():
                if report_content and isinstance(report_content, str):
                    verdict_match = re.search(r'VERDICT:\s*\{[^}]*"direction":\s*"([^"]+)"', report_content)
                    if verdict_match:
                        direction = verdict_match.group(1)
                        if "偏多" in direction or "买入" in direction:
                            return "BUY", f"{report_name}建议: {direction}"
                        elif "偏空" in direction or "卖出" in direction:
                            return "SELL", f"{report_name}建议: {direction}"

            # 检查final_trade_decision
            if "final_trade_decision" in response:
                ftd = response["final_trade_decision"]
                if isinstance(ftd, dict):
                    decision = ftd.get("decision", "UNKNOWN")
                    rationale = ftd.get("rationale", str(ftd))
                    return str(decision).upper(), str(rationale)[:200]

            return "ANALYZED", json.dumps(response, ensure_ascii=False)[:200]
    except Exception as e:
        return "ERROR", f"解析错误: {e}"

    return "ERROR", "无法解析响应"

def main():
    print("=" * 60)
    print("自选股分析 - 前20只A股")
    print("=" * 60)

    # Load and filter
    watchlist = load_watchlist()
    a_shares = [item for item in watchlist if is_a_share(item)]
    print(f"总自选股: {len(watchlist)}")
    print(f"A股股票: {len(a_shares)}")
    print(f"分析前{MAX_STOCKS}只:")
    print()

    targets = a_shares[:MAX_STOCKS]
    for i, s in enumerate(targets):
        print(f"  {i+1}. {s['code']} ({s['market']}) - 价格: {s.get('price', 'N/A')}")

    # Ensure output directory exists
    import os
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)

    # Analyze each stock
    results = []
    success = 0
    failed = 0

    for i, stock in enumerate(targets):
        code = stock["code"]
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(targets)}] 分析 {code} ({stock['market']})...")
        print(f"{'='*50}")

        start_time = time.time()
        response = call_api(code)
        elapsed = time.time() - start_time

        if response:
            decision, rationale = extract_decision(response)
            status = "成功"
            success += 1
            print(f"  结果: {decision}")
            print(f"  耗时: {elapsed:.1f}s")
        else:
            decision = "ERROR"
            rationale = "API调用失败"
            status = "失败"
            failed += 1
            print(f"  失败! 耗时: {elapsed:.1f}s")

        results.append({
            "序号": i + 1,
            "代码": code,
            "市场": stock["market"],
            "价格": stock.get("price", ""),
            "建议": decision,
            "摘要": rationale,
            "状态": status,
            "耗时(s)": f"{elapsed:.1f}"
        })

        # Brief pause between requests
        if i < len(targets) - 1:
            time.sleep(2)

    # Write CSV
    print(f"\n写入CSV: {CSV_OUTPUT}")
    with open(CSV_OUTPUT, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=["序号", "代码", "市场", "价格", "建议", "摘要", "状态", "耗时(s)"])
        writer.writeheader()
        writer.writerows(results)

    # Write MD summary
    print(f"写入MD: {MD_OUTPUT}")
    buy_list = [r for r in results if r["建议"] in ("BUY", "买入")]
    sell_list = [r for r in results if r["建议"] in ("SELL", "卖出")]
    hold_list = [r for r in results if r["建议"] in ("HOLD", "持有")]

    with open(MD_OUTPUT, 'w', encoding='utf-8') as f:
        f.write(f"# 自选股分析摘要 - {TRADE_DATE_FMT}\n\n")
        f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 统计\n\n")
        f.write(f"- 总分析: {len(results)} 只\n")
        f.write(f"- 成功: {success} 只\n")
        f.write(f"- 失败: {failed} 只\n")
        f.write(f"- 买入建议: {len(buy_list)} 只\n")
        f.write(f"- 卖出建议: {len(sell_list)} 只\n")
        f.write(f"- 持有建议: {len(hold_list)} 只\n\n")

        f.write(f"## 分析结果\n\n")
        f.write(f"| 序号 | 代码 | 市场 | 价格 | 建议 | 状态 |\n")
        f.write(f"|------|------|------|------|------|------|\n")
        for r in results:
            f.write(f"| {r['序号']} | {r['代码']} | {r['市场']} | {r['价格']} | {r['建议']} | {r['状态']} |\n")

        if buy_list:
            f.write(f"\n## 推荐买入\n\n")
            for r in buy_list:
                f.write(f"### {r['代码']} ({r['市场']}) - 价格: {r['价格']}\n")
                f.write(f"{r['摘要']}\n\n")

        # Write top 5 recommendations (by any positive signal)
        positive = [r for r in results if r["建议"] in ("BUY", "买入", "HOLD", "持有") and r["状态"] == "成功"]
        if positive:
            f.write(f"\n## 前5名推荐\n\n")
            for r in positive[:5]:
                f.write(f"1. **{r['代码']}** ({r['市场']}) - {r['建议']} - 价格: {r['价格']}\n")

    # Print summary
    print(f"\n{'='*60}")
    print("分析完成!")
    print(f"{'='*60}")
    print(f"成功: {success}/{len(results)}")
    print(f"失败: {failed}/{len(results)}")

    if buy_list:
        print(f"\n买入建议:")
        for r in buy_list:
            print(f"  {r['代码']} ({r['市场']}) - {r['摘要'][:80]}")

    if sell_list:
        print(f"\n卖出建议:")
        for r in sell_list:
            print(f"  {r['代码']} ({r['市场']}) - {r['摘要'][:80]}")

    return success, failed, results

if __name__ == "__main__":
    main()
