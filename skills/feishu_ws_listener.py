#!/usr/bin/env python3
"""
飞书消息监听服务 - WebSocket 长链接版本
使用 lark-cli event consume 实现实时消息接收
"""
import sys
import os
import json
import subprocess
import signal
from datetime import datetime

sys.path.insert(0, '/home/jiaod/qts')

LARK_CLI = "/home/jiaod/.npm-global/bin/lark-cli"
CHAT_ID = "oc_d2e8df3c676afa2c352d8ece0a9b6141"
WORK_DIR = "/home/jiaod/qts"

# 全局状态
running = True

def signal_handler(sig, frame):
    global running
    print("\n收到停止信号，正在退出...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(msg):
    """日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def send_message(chat_id, content, msg_type="markdown"):
    """发送消息"""
    cmd = [
        LARK_CLI, "im", "+messages-send",
        f"--{msg_type}", content,
        "--as", "bot"
    ]
    
    if chat_id.startswith("oc_"):
        cmd.extend(["--chat-id", chat_id])
    else:
        cmd.extend(["--user-id", chat_id])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("ok", False)
    except Exception as e:
        log(f"发送消息失败: {e}")
    return False

def send_file(chat_id, file_path):
    """发送文件"""
    import shutil
    file_name = os.path.basename(file_path)
    dest = os.path.join(WORK_DIR, file_name)
    shutil.copy2(file_path, dest)
    
    cmd = [
        LARK_CLI, "im", "+messages-send",
        "--file", file_name,
        "--as", "bot"
    ]
    
    if chat_id.startswith("oc_"):
        cmd.extend(["--chat-id", chat_id])
    else:
        cmd.extend(["--user-id", chat_id])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("ok", False)
    except Exception as e:
        log(f"发送文件失败: {e}")
    return False

def handle_command(chat_id, content):
    """处理命令"""
    content = content.strip().lower()
    
    # 生成报告
    if "生成报告" in content or "generate" in content:
        return cmd_generate_report(chat_id)
    
    # 发送报告
    if "发送报告" in content or "send" in content:
        return cmd_send_report(chat_id)
    
    # 帮助
    if "帮助" in content or "help" in content:
        return cmd_help()
    
    # 状态
    if "状态" in content or "status" in content:
        return cmd_status()
    
    return None

def cmd_generate_report(chat_id):
    """生成报告命令"""
    try:
        log("开始生成报告...")
        send_message(chat_id, "⏳ 正在生成市场报告，请稍候...")
        
        from skills.market_report import generate_report
        
        # 检查是否有最新的 Markdown 报告
        md_file = "/tmp/latest_report.md"
        if not os.path.exists(md_file):
            # 尝试从 API 获取
            import requests
            try:
                resp = requests.get("http://localhost:8000/v1/market/insight", timeout=120)
                if resp.status_code == 200:
                    with open(md_file, "w", encoding="utf-8") as f:
                        f.write(resp.text)
                else:
                    return "❌ 无法获取市场数据"
            except:
                return "❌ TradingAgents 服务未运行"
        
        output_file = f"{WORK_DIR}/report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        generate_report(md_file, output_file, datetime.now().strftime('%Y年%m月%d日'))
        
        log(f"报告已生成: {output_file}")
        return f"✅ 报告已生成\n文件: {os.path.basename(output_file)}"
    except Exception as e:
        log(f"生成报告失败: {e}")
        return f"❌ 生成报告失败: {e}"

def cmd_send_report(chat_id):
    """发送报告命令"""
    try:
        import glob
        reports = glob.glob(f"{WORK_DIR}/report_*.html")
        if not reports:
            return "❌ 未找到 HTML 报告，请先执行生成报告命令"
        
        latest_report = max(reports, key=os.path.getctime)
        log(f"发送报告: {latest_report}")
        
        if send_file(chat_id, latest_report):
            return f"✅ 报告已发送\n文件: {os.path.basename(latest_report)}"
        else:
            return "❌ 发送失败"
    except Exception as e:
        log(f"发送报告失败: {e}")
        return f"❌ 发送报告失败: {e}"

def cmd_help():
    """帮助命令"""
    return """📋 **可用命令**

| 命令 | 功能 |
|------|------|
| 生成报告 | 生成最新的市场洞察报告 |
| 发送报告 | 将报告发送到飞书群 |
| 状态 | 查看系统状态 |
| 帮助 | 显示此帮助信息 |

💡 直接发送文本消息即可触发命令"""

def cmd_status():
    """状态命令"""
    import glob
    reports = glob.glob(f"{WORK_DIR}/report_*.html")
    latest = max(reports, key=os.path.getctime) if reports else "无"
    
    return f"""📊 **系统状态**

- Docker 容器: 运行中
- 报告数量: {len(reports)} 份
- 最新报告: {os.path.basename(latest)}
- 监听模式: WebSocket 长链接"""

def process_event(event_data):
    """处理事件"""
    try:
        # 解析事件
        chat_id = event_data.get("chat_id", "")
        content = event_data.get("content", "")
        sender = event_data.get("sender", {})
        msg_type = event_data.get("message_type", "")
        
        # 只处理文本消息
        if msg_type != "text":
            return
        
        # 处理命令
        response = handle_command(chat_id, content)
        if response:
            log(f"收到命令: {content[:50]}")
            send_message(chat_id, response)
    except Exception as e:
        log(f"处理事件失败: {e}")

def main():
    """主函数"""
    log("=" * 50)
    log("飞书 WebSocket 监听服务启动")
    log("使用长链接，无需公网URL")
    log("=" * 50)
    
    # 启动事件消费（保持 stdin 打开）
    cmd = [
        LARK_CLI, "event", "consume",
        "im.message.receive_v1",
        "--as", "bot",
        "--timeout", "0"  # 无超时
    ]
    
    try:
        # 使用 /dev/null 作为 stdin 保持打开
        with open(os.devnull, 'r') as devnull:
            process = subprocess.Popen(
                cmd,
                stdin=devnull,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=WORK_DIR
            )
        
        log("事件消费已启动，等待消息...")
        
        # 读取输出
        while running:
            line = process.stdout.readline()
            if not line:
                break
            
            try:
                event_data = json.loads(line.strip())
                process_event(event_data)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"处理输出失败: {e}")
        
        # 清理
        process.terminate()
        process.wait()
        
    except KeyboardInterrupt:
        log("收到中断信号")
    except Exception as e:
        log(f"服务异常: {e}")
    
    log("服务已停止")

if __name__ == "__main__":
    main()
