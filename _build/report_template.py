#!/usr/bin/env python3
"""
市场洞察报告 HTML 生成器 - 完整版
从 Markdown 报告生成带仪表盘、示意图的完整 HTML 报告
"""
import sys
import re
from datetime import datetime

def extract_md_section(text, start_pattern, end_pattern=None):
    """从 Markdown 中提取指定部分"""
    if end_pattern:
        match = re.search(f'{start_pattern}(.*?)(?={end_pattern}|$)', text, re.DOTALL)
    else:
        match = re.search(f'{start_pattern}(.*)', text, re.DOTALL)
    return match.group(1).strip() if match else ''

def parse_events(md_text):
    """解析事件驱动分析"""
    events = []
    # 匹配事件块
    event_blocks = re.findall(r'\*\*事件名称\*\*[：:](.*?)\n.*?\*\*事件背景\*\*[：:](.*?)\n.*?\*\*影响传导链\*\*[：:](.*?)\n.*?\*\*影响方向\*\*[：:](.*?)(?:\n|\*\*)', md_text, re.DOTALL)
    
    for name, background, chain, direction in event_blocks:
        events.append({
            'name': name.strip(),
            'background': background.strip(),
            'chain': chain.strip(),
            'direction': direction.strip()
        })
    return events

def parse_sentiment(md_text):
    """解析情绪分析"""
    sentiment = {}
    
    # 情绪温度
    temp_match = re.search(r'情绪温度.*?[：:](.*?)(?:\n|$)', md_text)
    sentiment['temperature'] = temp_match.group(1).strip() if temp_match else '中性'
    
    # 涨跌比
    ratio_match = re.search(r'涨跌比.*?[：:](.*?)(?:\n\n|\n\*)', md_text, re.DOTALL)
    sentiment['ratio'] = ratio_match.group(1).strip() if ratio_match else ''
    
    # 成交量
    volume_match = re.search(r'成交量特征.*?[：:](.*?)(?:\n\n|\n\*)', md_text, re.DOTALL)
    sentiment['volume'] = volume_match.group(1).strip() if volume_match else ''
    
    # 涨停
    limit_match = re.search(r'涨停.*?跌停.*?[：:](.*?)(?:\n\n|\n\*)', md_text, re.DOTALL)
    sentiment['limit'] = limit_match.group(1).strip() if limit_match else ''
    
    return sentiment

def parse_fund_flow(md_text):
    """解析资金分析"""
    fund = {}
    
    flow_match = re.search(r'主力资金流向判断.*?[：:](.*?)(?:\n|$)', md_text)
    fund['flow'] = flow_match.group(1).strip() if flow_match else '中性'
    
    return fund

def parse_conclusion(md_text):
    """解析综合评判"""
    conclusion = {}
    
    # 最终结论
    conclusion_match = re.search(r'明确结论.*?[：:](.*?)(?:\n|$)', md_text)
    conclusion['direction'] = conclusion_match.group(1).strip() if conclusion_match else '中性'
    
    # 核心理由
    reason_match = re.search(r'核心理由.*?[：:](.*?)(?:\n|$)', md_text)
    conclusion['reason'] = reason_match.group(1).strip() if reason_match else ''
    
    return conclusion

def parse_views(md_text):
    """解析多空观点"""
    views = {'bull': '', 'bear': '', 'judgment': ''}
    
    # 多方观点
    bull_match = re.search(r'多方.*?观点.*?[：:](.*?)(?=\n\*|\n###|\n##)', md_text, re.DOTALL)
    if bull_match:
        views['bull'] = bull_match.group(1).strip()
    
    # 空方观点
    bear_match = re.search(r'空方.*?观点.*?[：:](.*?)(?=\n\*|\n###|\n##)', md_text, re.DOTALL)
    if bear_match:
        views['bear'] = bear_match.group(1).strip()
    
    # 综合判断
    judgment_match = re.search(r'综合判断.*?[：:](.*?)(?=\n###|\n##)', md_text, re.DOTALL)
    if judgment_match:
        views['judgment'] = judgment_match.group(1).strip()
    
    return views

def parse_verification(md_text):
    """解析验证信号"""
    signals = {'up': {}, 'down': {}, 'neutral': {}}
    
    # 上涨信号
    up_section = extract_md_section(md_text, r'### 上涨趋势确认\n', r'### 下跌趋势确认')
    signals['up']['items'] = re.findall(r'\*\*(.*?)\*\*[：:](.*?)(?=\n\*|\n\n)', up_section, re.DOTALL)
    up_summary = re.search(r'一句话总结.*?[：:](.*?)(?=\n\n|\Z)', up_section, re.DOTALL)
    signals['up']['summary'] = up_summary.group(1).strip() if up_summary else ''
    
    # 下跌信号
    down_section = extract_md_section(md_text, r'### 下跌趋势确认\n', r'### 横盘震荡确认')
    signals['down']['items'] = re.findall(r'\*\*(.*?)\*\*[：:](.*?)(?=\n\*|\n\n)', down_section, re.DOTALL)
    down_summary = re.search(r'一句话总结.*?[：:](.*?)(?=\n\n|\Z)', down_section, re.DOTALL)
    signals['down']['summary'] = down_summary.group(1).strip() if down_summary else ''
    
    # 横盘信号
    neutral_section = extract_md_section(md_text, r'### 横盘震荡确认\n', r'## (?:二|三|$)')
    signals['neutral']['items'] = re.findall(r'\*\*(.*?)\*\*[：:](.*?)(?=\n\*|\n\n)', neutral_section, re.DOTALL)
    neutral_summary = re.search(r'一句话总结.*?[：:](.*?)(?=\n\n|\Z)', neutral_section, re.DOTALL)
    signals['neutral']['summary'] = neutral_summary.group(1).strip() if neutral_summary else ''
    
    return signals

def parse板块建议(md_text):
    """解析板块建议"""
    result = {'recommend': '', 'avoid': ''}
    
    recommend_match = re.search(r'推荐关注.*?[：:](.*?)(?=\n\*|\n##)', md_text, re.DOTALL)
    if recommend_match:
        result['recommend'] = recommend_match.group(1).strip()
    
    avoid_match = re.search(r'需要回避.*?[：:](.*?)(?=\n\*|\n##)', md_text, re.DOTALL)
    if avoid_match:
        result['avoid'] = avoid_match.group(1).strip()
    
    return result

def parse_risks(md_text):
    """解析风险提示"""
    risks = re.findall(r'\d+\.\s*\*\*(.*?)\*\*[：:](.*?)(?=\n\d+\.|\n##|\Z)', md_text, re.DOTALL)
    return [(name.strip(), content.strip()) for name, content in risks]

def parse_strategy(md_text):
    """解析操作策略"""
    strategy_match = re.search(r'仓位建议.*?[：:](.*?)(?:\n|$)', md_text)
    return strategy_match.group(1).strip() if strategy_match else ''

def parse_index_data(md_text):
    """解析指数数据"""
    rows = []
    # 匹配表格行
    table_match = re.search(r'## 指数数据\n\n\|(.*?)\n\|.*?\n((?:\|.*?\n)*)', md_text)
    if table_match:
        for row in table_match.group(2).strip().split('\n'):
            cells = [c.strip() for c in row.split('|')[1:-1]]
            if len(cells) >= 3:
                rows.append({'name': cells[0], 'price': cells[1], 'change': cells[2]})
    return rows

def get_temperature_width(temp_text):
    """根据情绪温度文本返回仪表盘宽度"""
    if '偏热' in temp_text or '亢奋' in temp_text:
        return 80
    elif '偏冷' in temp_text or '恐慌' in temp_text:
        return 20
    else:
        return 50

def get_fund_width(flow_text):
    """根据资金流向返回仪表盘宽度"""
    if '偏流入' in flow_text or '流入' in flow_text:
        return 70
    elif '偏流出' in flow_text or '流出' in flow_text:
        return 30
    else:
        return 50

def generate_html(md_text, date_str=None):
    """生成完整 HTML 报告"""
    if not date_str:
        date_str = datetime.now().strftime('%Y年%m月%d日')
    
    # 解析各部分
    index_data = parse_index_data(md_text)
    events = parse_events(md_text)
    sentiment = parse_sentiment(md_text)
    fund = parse_fund_flow(md_text)
    conclusion = parse_conclusion(md_text)
    views = parse_views(md_text)
    signals = parse_verification(md_text)
    board = parse板块建议(md_text)
    risks = parse_risks(md_text)
    strategy = parse_strategy(md_text)
    
    # 构建指数表格
    index_rows = ''
    for idx in index_data:
        change_class = 'up' if '+' in idx['change'] else 'down' if '-' in idx['change'] else ''
        index_rows += f'<tr><td><strong>{idx["name"]}</strong></td><td>{idx["price"]}</td><td class="{change_class}">{idx["change"]}</td></tr>\n'
    
    # 构建事件块
    events_html = ''
    for i, event in enumerate(events, 1):
        direction_class = 'up' if '偏多' in event['direction'] else 'down' if '偏空' in event['direction'] else ''
        events_html += f'''
        <div class="event-box">
            <h4>📌 事件{i}：{event["name"]}</h4>
            <p><strong>事件背景：</strong>{event["background"]}</p>
            <ul>
                <li><strong>影响传导链：</strong>{event["chain"]}</li>
                <li><strong>影响方向：</strong><span class="{direction_class}">{event["direction"]}</span></li>
            </ul>
        </div>'''
    
    # 构建情绪仪表盘
    temp_width = get_temperature_width(sentiment['temperature'])
    temp_class = 'bullish' if temp_width > 60 else 'bearish' if temp_width < 40 else 'neutral'
    temp_label = '偏热' if temp_width > 60 else '偏冷' if temp_width < 40 else '中性'
    
    sentiment_html = f'''
    <div class="gauge-container">
        <h4>🌡️ 情绪温度</h4>
        <p style="font-size: 13px; color: #666;">{sentiment.get("ratio", "") or sentiment.get("limit", "")}</p>
        <div class="gauge">
            <div class="gauge-fill {temp_class}" style="width: {temp_width}%;"></div>
        </div>
        <div class="gauge-label">
            <span>偏冷</span>
            <span style="color: #dc3545; font-weight: 600;">{temp_label} {temp_width}%</span>
            <span>偏热</span>
        </div>
    </div>'''
    
    # 构建资金仪表盘
    fund_width = get_fund_width(fund['flow'])
    fund_class = 'bullish' if fund_width > 60 else 'bearish' if fund_width < 40 else 'neutral'
    fund_label = '偏流入' if fund_width > 60 else '偏流出' if fund_width < 40 else '中性'
    
    fund_html = f'''
    <div class="gauge-container">
        <h4>💰 资金流向</h4>
        <p style="font-size: 13px; color: #666;">{fund.get("flow", "")}</p>
        <div class="gauge">
            <div class="gauge-fill {fund_class}" style="width: {fund_width}%;"></div>
        </div>
        <div class="gauge-label">
            <span>流出</span>
            <span style="color: #dc3545; font-weight: 600;">{fund_label} {fund_width}%</span>
            <span>流入</span>
        </div>
    </div>'''
    
    # 构建综合评判框
    conclusion_class = 'bearish' if '偏空' in conclusion['direction'] else ''
    conclusion_text = conclusion['direction']
    if '偏空' in conclusion['direction']:
        conclusion_text = '市场偏空，短期调整概率较大'
    elif '偏多' in conclusion['direction']:
        conclusion_text = '市场偏多，短期趋势向上'
    else:
        conclusion_text = '市场中性，方向不明朗'
    
    conclusion_html = f'''
    <div class="conclusion-box {conclusion_class}">
        <h3>📊 综合评判</h3>
        <p style="font-size: 18px; font-weight: 600;">{conclusion_text}</p>
        <p style="font-size: 13px; opacity: 0.9; margin-top: 8px;">{conclusion.get("reason", "")}</p>
    </div>'''
    
    # 构建验证信号
    def build_signal_list(items):
        html = '<ul>'
        for name, content in items:
            html += f'<li><strong>{name}：</strong>{content}</li>'
        html += '</ul>'
        return html
    
    # 构建风险提示
    risks_html = ''
    for i, (name, content) in enumerate(risks, 1):
        risks_html += f'<div class="risk-item"><strong>{i}. {name}：</strong>{content}</div>\n'
    
    # 生成完整 HTML
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
        .gauge-container {{ background: #f5f5f5; padding: 14px; border-radius: 8px; margin: 10px 0; }}
        .gauge {{ height: 24px; border-radius: 12px; background: #e0e0e0; position: relative; overflow: hidden; margin: 8px 0; }}
        .gauge-fill {{ height: 100%; border-radius: 12px; }}
        .gauge-fill.bullish {{ background: linear-gradient(90deg, #ff6b6b, #dc3545); }}
        .gauge-fill.bearish {{ background: linear-gradient(90deg, #66bb6a, #28a745); }}
        .gauge-fill.neutral {{ background: linear-gradient(90deg, #ffa726, #ff9800); }}
        .gauge-label {{ display: flex; justify-content: space-between; font-size: 12px; color: #666; }}
        .signal-box {{ background: #f5f5f5; padding: 14px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #2196f3; }}
        .signal-box h4 {{ color: #1565c0; margin-bottom: 8px; font-size: 14px; }}
        .signal-box.up {{ border-left-color: #dc3545; }}
        .signal-box.up h4 {{ color: #c62828; }}
        .signal-box.down {{ border-left-color: #28a745; }}
        .signal-box.down h4 {{ color: #2e7d32; }}
        .signal-box.neutral {{ border-left-color: #ff9800; }}
        .signal-box.neutral h4 {{ color: #e65100; }}
        .event-box {{ background: #f5f5f5; padding: 14px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #2196f3; }}
        .event-box h4 {{ color: #1565c0; margin-bottom: 8px; font-size: 14px; }}
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
                    {index_rows}
                </table>
            </div>

            <div class="section">
                <h2 class="section-title">二、事件联动分析</h2>
                {events_html}
                {sentiment_html}
                {fund_html}
                {conclusion_html}
            </div>

            <div class="section">
                <h2 class="section-title">三、核心分析</h2>
                <div class="bull-box">
                    <h4>🔴 多方观点</h4>
                    <p>{views.get("bull", "")}</p>
                </div>
                <div class="bear-box">
                    <h4>🟢 空方观点</h4>
                    <p>{views.get("bear", "")}</p>
                </div>
                <div class="analysis">
                    <p><strong>综合判断：</strong>{views.get("judgment", "")}</p>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">四、板块建议</h2>
                <div class="analysis">
                    <p><strong>🔴 建议关注：</strong>{board.get("recommend", "")}</p>
                    <p><strong>🟢 坚决回避：</strong>{board.get("avoid", "")}</p>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">五、操作策略</h2>
                <div class="strategy-box">
                    <p><strong>仓位建议：{strategy}</strong></p>
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
                    {build_signal_list(signals["up"].get("items", []))}
                    <p><strong>一句话总结：</strong>{signals["up"].get("summary", "")}</p>
                </div>
                <div class="signal-box down">
                    <h4>📉 下跌趋势确认</h4>
                    {build_signal_list(signals["down"].get("items", []))}
                    <p><strong>一句话总结：</strong>{signals["down"].get("summary", "")}</p>
                </div>
                <div class="signal-box neutral">
                    <h4>↔️ 横盘震荡确认</h4>
                    {build_signal_list(signals["neutral"].get("items", []))}
                    <p><strong>一句话总结：</strong>{signals["neutral"].get("summary", "")}</p>
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
    """主函数"""
    if len(sys.argv) < 3:
        print("用法: python report_template.py <input.md> <output.html> [date]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    date_str = sys.argv[3] if len(sys.argv) > 3 else None
    
    with open(input_file, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    html = generate_html(md_text, date_str)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"报告已生成: {output_file}")


if __name__ == '__main__':
    main()
