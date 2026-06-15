#!/usr/bin/env python3
"""
市场洞察报告生成模块
从 Markdown 报告生成带可视化图表的 HTML 报告
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _build.report_template import generate_html


def generate_report(md_file: str, output_file: str, date_str: str = None) -> str:
    """从 Markdown 文件生成 HTML 报告
    
    Args:
        md_file: Markdown 报告文件路径
        output_file: 输出 HTML 文件路径
        date_str: 日期字符串（可选）
    
    Returns:
        str: 输出文件路径
    """
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    html = generate_html(md_text, date_str)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_file


def generate_report_from_string(md_text: str, output_file: str, date_str: str = None) -> str:
    """从 Markdown 字符串生成 HTML 报告
    
    Args:
        md_text: Markdown 格式的报告内容
        output_file: 输出 HTML 文件路径
        date_str: 日期字符串（可选）
    
    Returns:
        str: 输出文件路径
    """
    html = generate_html(md_text, date_str)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_file
