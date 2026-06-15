#!/usr/bin/env python3
"""
市场洞察报告 HTML 生成器
从 Markdown 报告生成固定格式的 HTML 报告
"""
import sys
import re
import os

def md_to_html_content(md_text):
    """将 Markdown 报告转换为 HTML 内容块"""
    
    # 提取各部分
    def extract(text, start, end=None):
        if end:
            match = re.search(f'{start}(.*?)(?={end}|$)', text, re.DOTALL)
        else:
            match = re.search(f'{start}(.*)', text, re.DOTALL)
        return match.group(1).strip() if match else ''
    
    # 提取指数数据
    index_match = re.search(r'## 指数数据\n\n\|(.*?)\n\|.*?\n((?:\|.*?\n)*)', md_text)
    index_rows = ''
    if index_match:
        rows = index_match.group(2).strip().split('\n')
        for row in rows:
            cells = [c.strip() for c in row.split('|')[1:-1]]
            if len(cells) >= 3:
                name, price, change = cells[0], cells[1], cells[2]
                change_class = 'up' if '+' in change else 'down' if '-' in change else ''
                index_rows += f'<tr><td><strong>{name}</strong></td><td>{price}</td><td class="{change_class}">{change}</td></tr>\n'
    
    # 提取核心分析
    core_analysis = extract(md_text, r'## 核心分析\n\n', r'## 因果联动分析')
    
    # 提取事件驱动分析
    events = re.findall(r'\*\*事件名称\*\*[：:](.*?)\n.*?\*\*事件背景\*\*[：:](.*?)\n.*?\*\*影响传导链\*\*[：:](.*?)\n.*?\*\*影响方向\*\*[：:](.*?)(?:\n|\*)', md_text, re.DOTALL)
    
    events_html = ''
    for i, (name, background, chain, direction) in enumerate(events, 1):
        direction = direction.strip()
        direction_class = 'up' if '偏多' in direction else 'down' if '偏空' in direction else ''
        events_html += f'''
        <div class="event-box">
            <h4>📌 事件{i}：{name.strip()}</h4>
            <p><strong>事件背景：</strong>{background.strip()}</p>
            <ul>
                <li><strong>影响传导链：</strong>{chain.strip()}</li>
                <li><strong>影响方向：</strong><span class="{direction_class}">{direction}</span></li>
            </ul>
        </div>'''
    
    # 提取验证信号
    def extract_signal(text, section_name):
        section = extract(text, f'### {section_name}\n', r'### (?:上涨|下跌|横盘)')
        if not section:
            section = extract(text, f'### {section_name}\n', r'## (?:二|三|$)')
        items = re.findall(r'\*\*(.*?)\*\*[：:](.*?)(?=\n\*|\n\n|\Z)', section, re.DOTALL)
        summary = re.search(r'一句话总结[：:](.*?)(?=\n\n|\Z)', section, re.DOTALL)
        summary_text = summary.group(1).strip() if summary else ''
        return items, summary_text
    
    up_items, up_summary = extract_signal(md_text, '上涨趋势确认')
    down_items, down_summary = extract_signal(md_text, '下跌趋势确认')
    neutral_items, neutral_summary = extract_signal(md_text, '横盘震荡确认')
    
    def build_signal_list(items):
        html = '<ul>'
        for name, content in items:
            html += f'<li><strong>{name}：</strong>{content.strip()}</li>'
        html += '</ul>'
        return html
    
    # 提取多空观点
    bull_match = re.search(r'\*\*多方.*?观点\*\*[：:](.*?)(?=\n\*|\n###|\n##)', md_text, re.DOTALL)
    bear_match = re.search(r'\*\*空方.*?观点\*\*[：:](.*?)(?=\n\*|\n###|\n##)', md_text, re.DOTALL)
    bull_view = bull_match.group(1).strip() if bull_match else ''
    bear_view = bear_match.group(1).strip() if bear_match else ''
    
    # 提取综合判断
    judgment_match = re.search(r'### 3\. 综合判断[：:](.*?)(?=\n###|\n##)', md_text, re.DOTALL)
    judgment = judgment_match.group(1).strip() if judgment_match else ''
    
    # 提取板块建议
    recommend_match = re.search(r'\*\*推荐关注\*\*[：:](.*?)(?=\n\*|\n##)', md_text, re.DOTALL)
    avoid_match = re.search(r'\*\*需要回避\*\*[：:](.*?)(?=\n\*|\n##)', md_text, re.DOTALL)
    recommend = recommend_match.group(1).strip() if recommend_match else ''
    avoid = avoid_match.group(1).strip() if avoid_match else ''
    
    # 提取操作策略
    strategy_match = re.search(r'### 5\. 操作策略.*?\*\*仓位建议\*\*[：:](.*?)(?=\n\*|\n##)', md_text, re.DOTALL)
    strategy = strategy_match.group(1).strip() if strategy_match else ''
    
    # 提取风险提示
    risks = re.findall(r'\d+\.\s*\*\*(.*?)\*\*[：:](.*?)(?=\n\d+\.|\n##|\Z)', md_text, re.DOTALL)
    
    return {
        'index_rows': index_rows,
        'events_html': events_html,
        'core_analysis': core_analysis,
        'bull_view': bull_view,
        'bear_view': bear_view,
        'judgment': judgment,
        'recommend': recommend,
        'avoid': avoid,
        'strategy': strategy,
        'risks': risks,
        'up_items': up_items,
        'up_summary': up_summary,
        'down_items': down_items,
        'down_summary': down_summary,
        'neutral_items': neutral_items,
        'neutral_summary': neutral_summary,
    }


def generate_html(data, date_str=None):
    """生成完整 HTML 报告"""
    if not date_str:
        from datetime import datetime
        date_str = datetime.now().strftime('%Y年%m月%d日')
    
    # 构建风险提示 HTML
    risks_html = ''
    for i, (name, content) in enumerate(data.get('risks', []), 1):
        risks_html += f'<div class="risk-item"><strong>{i}. {name}：</strong>{content.strip()}</div>\n'
    
    # 构建验证信号 HTML
    def build_signal_list(items):
        html = '<ul>'
        for name, content in items:
            html += f'<li><strong>{name}：</strong>{content.strip()}</li>'
        html += '</ul>'
        return html
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>全市场洞察报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.9; color: #1a1a1a; background: #f0f2f5; padding: 12px; font-size: 14px; }}
        .container {{ max-width: 100%; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: #fff; padding: 20px 16px; text-align: center; }}
        .header h1 {{ font-size: 20px; margin-bottom: 6px; }}
        .header .date {{ font-size: 13px; opacity: 0.9; }}
        .content {{ padding: 16px; }}
        .section {{ margin-bottom: 20px; }}
        .section-title {{ font-size: 16px; color: #1e3c72; border-left: 4px solid #2a5298; padding-left: 10px; margin-bottom: 12px; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }}
        th {{ background: #f8f9fa; padding: 8px 6px; text-align: left; border-bottom: 2px solid #dee2e6; font-weight: 600; }}
        td {{ padding: 8px 6px; border-bottom: 1px solid #e9ecef; }}
        .up {{ color: #dc3545; }}
        .down {{ color: #28a745; }}
        .analysis {{ color: #2c3e50; font-size: 14px; }}
        .analysis p {{ margin-bottom: 12px; text-align: justify; }}
        .analysis strong {{ color: #1a1a1a; }}
        .highlight {{ background: #fff3cd; padding: 2px 6px; border-radius: 4px; color: #856404; }}
        .bull-box {{ background: #ffebee; border-left: 4px solid #dc3545; padding: 12px 14px; border-radius: 0 8px 8px 0; margin-bottom: 10px; }}
        .bull-box h4 {{ color: #c62828; font-size: 14px; margin-bottom: 6px; }}
        .bear-box {{ background: #e8f5e9; border-left: 4px solid #28a745; padding: 12px 14px; border-radius: 0 8px 8px 0; margin-bottom: 10px; }}
        .bear-box h4 {{ color: #2e7d32; font-size: 14px; margin-bottom: 6px; }}
        .strategy-box {{ background: #fff8e1; border-left: 4px solid #ffc107; padding: 12px 14px; border-radius: 0 8px 8px 0; margin-bottom: 10px; }}
        .risk-item {{ background: #ffebee; border-left: 4px solid #e53935; padding: 10px 12px; margin-bottom: 8px; border-radius: 0 6px 6px 0; font-size: 13px; color: #b71c1c; }}
        .conclusion-box {{ background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%); color: #fff; padding: 16px; border-radius: 8px; text-align: center; margin: 15px 0; }}
        .conclusion-box.bearish {{ background: linear-gradient(135deg, #dc3545 0%, #c62828 100%); }}
        .conclusion-box h3 {{ margin-bottom: 8px; }}
        .event-box {{ background: #f5f5f5; padding: 14px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #2196f3; }}
        .event-box h4 {{ color: #1565c0; margin-bottom: 8px; font-size: 14px; }}
        .signal-box {{ background: #f5f5f5; padding: 14px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #2196f3; }}
        .signal-box h4 {{ color: #1565c0; margin-bottom: 8px; font-size: 14px; }}
        .signal-box.up {{ border-left-color: #dc3545; }}
        .signal-box.up h4 {{ color: #c62828; }}
        .signal-box.down {{ border-left-color: #28a745; }}
        .signal-box.down h4 {{ color: #2e7d32; }}
        .signal-box.neutral {{ border-left-color: #ff9800; }}
        .signal-box.neutral h4 {{ color: #e65100; }}
        .footer {{ background: #f5f5f5; padding: 14px; text-align: center; color: #666; font-size: 11px; border-top: 1px solid #e0e0e0; }}
        ul {{ padding-left: 18px; margin: 6px 0; }}
        li {{ margin-bottom: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 全市场洞察报告</h1>
            <div class="date">{date_str} | TradingAgents 多Agent协同分析</div>
        </div>
        <div class="content">

            <div class="section">
                <h2 class="section-title">一、指数数据</h2>
                <table>
                    <tr><th>指数</th><th>收盘点数</th><th>涨跌幅</th></tr>
                    {data.get('index_rows', '')}
                </table>
            </div>

            <div class="section">
                <h2 class="section-title">二、事件联动分析</h2>
                {data.get('events_html', '')}
            </div>

            <div class="section">
                <h2 class="section-title">三、核心分析</h2>
                <div class="bull-box">
                    <h4>🔴 多方观点</h4>
                    <p>{data.get('bull_view', '')}</p>
                </div>
                <div class="bear-box">
                    <h4>🟢 空方观点</h4>
                    <p>{data.get('bear_view', '')}</p>
                </div>
                <div class="analysis">
                    <p><strong>综合判断：</strong>{data.get('judgment', '')}</p>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">四、板块建议</h2>
                <div class="analysis">
                    <p><strong>🔴 建议关注：</strong>{data.get('recommend', '')}</p>
                    <p><strong>🟢 坚决回避：</strong>{data.get('avoid', '')}</p>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">五、操作策略</h2>
                <div class="strategy-box">
                    <p><strong>仓位建议：{data.get('strategy', '')}</strong></p>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">六、风险提示</h2>
                {risks_html}
            </div>

            <div class="section">
                <h2 class="section-title">七、验证信号</h2>
                <div class="signal-box up">
                    <h4>📈 上涨趋势确认</h4>
                    {build_signal_list(data.get('up_items', []))}
                    <p><strong>一句话总结：</strong>{data.get('up_summary', '')}</p>
                </div>
                <div class="signal-box down">
                    <h4>📉 下跌趋势确认</h4>
                    {build_signal_list(data.get('down_items', []))}
                    <p><strong>一句话总结：</strong>{data.get('down_summary', '')}</p>
                </div>
                <div class="signal-box neutral">
                    <h4>↔️ 横盘震荡确认</h4>
                    {build_signal_list(data.get('neutral_items', []))}
                    <p><strong>一句话总结：</strong>{data.get('neutral_summary', '')}</p>
                </div>
            </div>

        </div>
        <div class="footer">
            <div>数据来源：同花顺、新浪财经 | 分析系统：TradingAgents 多Agent协作</div>
        </div>
    </div>
</body>
</html>'''
    
    return html


def main():
    """主函数：从 Markdown 生成 HTML"""
    if len(sys.argv) < 3:
        print("用法: python report_template.py <input.md> <output.html> [date]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    date_str = sys.argv[3] if len(sys.argv) > 3 else None
    
    # 读取 Markdown
    with open(input_file, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    # 转换为数据
    data = md_to_html_content(md_text)
    
    # 生成 HTML
    html = generate_html(data, date_str)
    
    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"报告已生成: {output_file}")


if __name__ == '__main__':
    main()
