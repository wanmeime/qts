# 飞书消息监听 Skill

## 功能
自动监听飞书群聊或私聊消息，支持命令响应和自动化工作流。

## 使用方法

### 监听群聊
```bash
python skills/feishu_listener.py --chat-id oc_xxxxxxxxxxxx
```

### 监听私聊
```bash
python skills/feishu_listener.py --user-id ou_xxxxxxxxxxxx
```

### Python 调用
```python
from skills.feishu_listener import FeishuListener

# 监听群聊
listener = FeishuListener(chat_id="oc_xxxxxxxxxxxx")

# 或监听私聊
listener = FeishuListener(user_id="ou_xxxxxxxxxxxx")

# 注册自定义命令
def my_handler(message):
    return "收到命令"

listener.register_command("我的命令", my_handler)

# 开始监听
listener.start_polling()
```

## 支持的命令

| 命令 | 功能 |
|------|------|
| 生成报告 | 生成最新的市场洞察报告 |
| 发送报告 | 将报告发送到飞书群 |
| 帮助 | 显示帮助信息 |

## 自定义命令

```python
def handle_custom(message):
    content = message.get("content", "")
    return f"你说了: {content}"

listener.register_command("自定义", handle_custom)
```

## 消息格式

监听器只处理文本消息，忽略 bot 自己发送的消息。

## 文件位置
- 监听器：`skills/feishu_listener.py`
- Skill 文档：`skills/feishu-listener/SKILL.md`
