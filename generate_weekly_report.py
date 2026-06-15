#!/usr/bin/env python3
"""
生成本周市场扫描报告
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# 添加项目路径
sys.path.insert(0, '/home/jiaod/qts')

# 导入市场数据采集
from _build.market_data_collector import MarketDataCollector, build_market_context
from _build.market_insight_graph import MarketInsightGraph, analyze_market_with_agents


async def main():
    """主流程"""
    print("=" * 60)
    print("开始生成本周市场扫描报告")
    print("=" * 60)

    # 1. 采集市场数据
    print("\n[1/3] 正在采集市场数据...")
    collector = MarketDataCollector()
    market_data = await collector.collect_all()
    print("✓ 市场数据采集完成")

    # 打印采集摘要
    scan_time = market_data.get("scan_time", "N/A")
    print(f"   数据时间: {scan_time}")

    # 2. 多Agent分析
    print("\n[2/3] 正在执行多Agent分析...")
    try:
        report_md = await analyze_market_with_agents(market_data)
        print("✓ 多Agent分析完成")
    except Exception as e:
        print(f"✗ 多Agent分析失败: {e}")
        # 降级方案：直接输出原始数据
        report_md = f"# 市场扫描报告（降级版）\n\n> 数据时间: {scan_time}\n\n## 市场数据概要\n\n{build_market_context(market_data)}"

    # 3. 生成HTML报告
    print("\n[3/3] 正在生成HTML报告...")
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    week_str = f"{datetime.now(timezone(timedelta(hours=8))).strftime('%Y年%m月第%W周')}"

    # 从Markdown构建HTML
    # 简单的markdown to html转换
    report_lines = report_md.split('\n')
    html_body_lines = []

    for line in report_lines:
        line = line.strip()
        if line.startswith('# '):
            html_body_lines.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '):
            html_body_lines.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('### '):
            html_body_lines.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('> '):
            html_body_lines.append(f'<blockquote>{line[2:]}</blockquote>')
        elif line.startswith('- '):
            html_body_lines.append(f'<li>{line[2:]}</li>')
        elif line.startswith('| ') and line.endswith(' |'):
            # 表格行 - 跳过markdown分隔符行
            if '---' not in line:
                cells = [c.strip() for c in line.strip('|').split('|')]
                html_body_lines.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')
        elif line == '':
            html_body_lines.append('')
        else:
            html_body_lines.append(f'<p>{line}</p>')

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>市场扫描报告 - {week_str}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            line-height: 1.8;
            color: #333;
            max-width: 960px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #f5f5f5;
        }}
        .report-container {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            padding: 40px;
        }}
        h1 {{
            color: #1a1a2e;
            border-bottom: 3px solid #e94560;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #16213e;
            margin-top: 35px;
            margin-bottom: 15px;
            padding-left: 10px;
            border-left: 4px solid #e94560;
        }}
        h3 {{
            color: #0f3460;
            margin-top: 25px;
        }}
        blockquote {{
            background: #f8f9fa;
            border-left: 4px solid #e94560;
            padding: 15px 20px;
            margin: 20px 0;
            color: #666;
            font-style: italic;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 0.95em;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 10px 12px;
            text-align: left;
        }}
        th {{
            background: #16213e;
            color: #fff;
        }}
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        li {{
            margin: 8px 0;
            list-style-position: inside;
        }}
        p {{
            margin: 12px 0;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #999;
            font-size: 0.85em;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="report-container">
        {chr(10).join(html_body_lines)}
        <div class="footer">
            <p>报告生成时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>本报告由量化交易系统自动生成，仅供参考，不构成投资建议</p>
        </div>
    </div>
</body>
</html>"""

    # 保存报告
    report_dir = '/home/jiaod/qts/30-信号/'
    report_filename = f'市场扫描报告_{today}.html'
    report_path = os.path.join(report_dir, report_filename)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✓ HTML报告已生成: {report_path}")
    print(f"\n报告文件: {report_path}")
    print(f"=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
