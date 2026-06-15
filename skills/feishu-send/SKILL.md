# 飞书消息发送 Skill

## 功能
使用 lark-cli 向飞书群发送文件或消息。

## 前置条件
- lark-cli 已安装：`/home/jiaod/.npm-global/bin/lark-cli`
- 已配置 bot 身份

## 使用方法

### 发送文件到飞书群
```bash
# 基本格式
lark-cli im +messages-send --chat-id <chat_id> --file <file_path> --as bot

# 示例
lark-cli im +messages-send --chat-id oc_xxxxxxxxxxxx --file report.html --as bot
```

### 发送 Markdown 消息
```bash
lark-cli im +messages-send --chat-id <chat_id> --markdown "消息内容" --as bot
```

### 发送文本消息
```bash
lark-cli im +messages-send --chat-id <chat_id> --text "消息内容" --as bot
```

## Python 封装

```python
import subprocess
import os

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"

def send_file_to_feishu(chat_id: str, file_path: str) -> dict:
    """发送文件到飞书群
    
    Args:
        chat_id: 飞书群 ID (oc_xxxxxxxx)
        file_path: 文件路径（绝对路径或相对路径）
    
    Returns:
        dict: {"ok": True/False, "message_id": "..."}
    """
    # 如果是 Windows 路径，转换为 WSL 路径
    if file_path.startswith("D:\\") or file_path.startswith("D:/"):
        file_path = file_path.replace("D:\\", "/mnt/d/").replace("D:/", "/mnt/d/")
    
    # 获取文件名（lark-cli 需要相对路径）
    file_name = os.path.basename(file_path)
    
    # 复制文件到当前目录（lark-cli 要求相对路径）
    import shutil
    shutil.copy2(file_path, f"/home/jiaod/qts/{file_name}")
    
    # 发送文件
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", chat_id,
        "--file", file_name,
        "--as", "bot"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if result.returncode == 0:
        import json
        return json.loads(result.stdout)
    else:
        return {"ok": False, "error": result.stderr}

def send_markdown_to_feishu(chat_id: str, content: str) -> dict:
    """发送 Markdown 消息到飞书群
    
    Args:
        chat_id: 飞书群 ID
        content: Markdown 格式内容
    
    Returns:
        dict: {"ok": True/False, "message_id": "..."}
    """
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--chat-id", chat_id,
        "--markdown", content,
        "--as", "bot"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if result.returncode == 0:
        import json
        return json.loads(result.stdout)
    else:
        return {"ok": False, "error": result.stderr}
```

## 常用 Chat ID

| 群名称 | Chat ID |
|--------|---------|
| QTS市场分析 | oc_d2e8df3c676afa2c352d8ece0a9b6141 |

## 注意事项
1. 文件必须是相对路径（lark-cli 限制）
2. 建议先复制文件到 `/home/jiaod/qts/` 目录再发送
3. 发送大文件可能需要较长时间

## 完整示例：生成报告并发送到飞书

```python
import subprocess
import shutil
import os

def generate_and_send_report(md_file: str, chat_id: str, date_str: str = None):
    """生成报告并发送到飞书
    
    Args:
        md_file: Markdown 报告文件路径
        chat_id: 飞书群 ID
        date_str: 日期字符串（可选）
    """
    # 1. 生成 HTML 报告
    from _build.report_template import generate_html
    
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    html = generate_html(md_text, date_str)
    
    # 2. 保存 HTML 文件
    html_file = f"/home/jiaod/qts/report_{date_str or 'latest'}.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # 3. 发送到飞书
    result = send_file_to_feishu(chat_id, html_file)
    
    if result.get('ok'):
        print(f"报告已发送到飞书群 {chat_id}")
        print(f"消息 ID: {result.get('data', {}).get('message_id')}")
    else:
        print(f"发送失败: {result}")
```

## 文件位置
- Skill 文档：`skills/feishu-send/SKILL.md`
