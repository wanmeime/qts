#!/usr/bin/env python3
"""Convert market report markdown to styled HTML."""

import re
import sys
from pathlib import Path

import markdown as md

INPUT = Path("/tmp/market_report_v2.md")
OUTPUT = Path("/home/jiaod/qts/30-信号/市场扫描报告_20260614.html")

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股市场扫描报告 — {title_date}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: #f0f2f5;
  color: #333;
  line-height: 1.7;
}}
.header {{
  background: #1a1a2e;
  color: #fff;
  padding: 40px 20px 30px;
  text-align: center;
}}
.header h1 {{
  font-size: 1.8rem;
  font-weight: 600;
  letter-spacing: 0.5px;
}}
.container {{
  max-width: 960px;
  margin: 0 auto;
  padding: 0 20px;
}}
.content {{
  background: #fff;
  margin: -20px auto 0;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  padding: 32px 40px 40px;
}}
@media (max-width: 640px) {{
  .content {{ padding: 20px 16px 28px; }}
  .header h1 {{ font-size: 1.3rem; }}
}}
h2 {{
  font-size: 1.25rem;
  color: #1a1a2e;
  border-left: 4px solid #e94560;
  padding-left: 12px;
  margin: 32px 0 16px;
}}
h2:first-child {{ margin-top: 0; }}
h3 {{
  font-size: 1.05rem;
  color: #2c3e6b;
  margin: 24px 0 10px;
}}
h1 {{ font-size: 1.4rem; margin: 28px 0 14px; color: #1a1a2e; }}
p, li {{ font-size: 0.95rem; margin-bottom: 8px; }}
ul, ol {{ padding-left: 24px; margin-bottom: 12px; }}
li {{ margin-bottom: 4px; }}
ul ul, ul ol, ol ul, ol ol {{ margin-top: 4px; margin-bottom: 4px; }}
blockquote {{
  border-left: 4px solid #e94560;
  background: #fdf0f2;
  padding: 12px 16px;
  margin: 16px 0;
  border-radius: 0 6px 6px 0;
  color: #555;
}}
blockquote p {{ margin-bottom: 0; }}
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0 20px;
  font-size: 0.9rem;
}}
th {{
  background: #1a1a2e;
  color: #fff;
  padding: 10px 12px;
  text-align: left;
  font-weight: 500;
}}
td {{
  padding: 9px 12px;
  border-bottom: 1px solid #e8e8e8;
}}
tr:nth-child(even) {{ background: #f7f8fa; }}
tr:hover {{ background: #eef1f5; }}
hr {{
  border: none;
  border-top: 1px solid #ddd;
  margin: 24px 0;
}}
strong {{ color: #1a1a2e; }}
.footer {{
  text-align: center;
  padding: 24px 20px;
  color: #888;
  font-size: 0.82rem;
}}
</style>
</head>
<body>
<div class="header">
  <h1>A股市场扫描报告</h1>
</div>
<div class="container">
<div class="content">
{body}
</div>
</div>
<div class="footer">
  报告生成时间: 2026-06-14 | 本报告由量化交易系统自动生成，仅供参考，不构成投资建议
</div>
</body>
</html>
"""


def main():
    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found", file=sys.stderr)
        sys.exit(1)

    md_text = INPUT.read_text(encoding="utf-8")

    # Skip the first # title line (we use our own title in header)
    md_text = re.sub(r"^# .+\n", "", md_text, count=1)

    body_html = md.markdown(md_text, extensions=["tables", "fenced_code"])
    full_html = HTML_TEMPLATE.format(body=body_html, title_date="2026年6月14日")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(full_html, encoding="utf-8")

    size = OUTPUT.stat().st_size
    print(f"Written: {OUTPUT}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
