#!/bin/bash
# ============================================================
# 启动盯盘相关服务
# 用法: bash 50-盯盘/start_services.sh
# 可添加到 crontab @reboot 实现 WSL 开机自启
# ============================================================

QTS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$QTS_DIR/50-盯盘/logs"
mkdir -p "$LOG_DIR"

echo "========================================"
echo "启动盯盘服务"
echo "项目目录: $QTS_DIR"
echo "日志目录: $LOG_DIR"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 1. 启动 Dashboard (端口 8891)
DASHBOARD_PID=$(pgrep -f "dashboard_server.py" 2>/dev/null)
if [ -z "$DASHBOARD_PID" ]; then
    echo "[Dashboard] 启动中..."
    cd "$QTS_DIR" && nohup python3 50-盯盘/dashboard_server.py \
        > "$LOG_DIR/dashboard.log" 2>&1 &
    sleep 2
    if pgrep -f "dashboard_server.py" > /dev/null 2>&1; then
        echo "[Dashboard] ✅ 启动成功 (端口 8891)"
    else
        echo "[Dashboard] ❌ 启动失败，请检查日志: $LOG_DIR/dashboard.log"
    fi
else
    echo "[Dashboard] ✅ 已在运行中 (PID: $DASHBOARD_PID)"
fi

# 2. 启动盯盘后台 (watchdog)
WATCHDOG_PID=$(pgrep -f "watchdog.py" 2>/dev/null)
if [ -z "$WATCHDOG_PID" ]; then
    echo "[盯盘后台] 启动中..."
    cd "$QTS_DIR" && nohup python3 50-盯盘/watchdog.py \
        > "$LOG_DIR/watchdog.log" 2>&1 &
    sleep 3
    if pgrep -f "watchdog.py" > /dev/null 2>&1; then
        echo "[盯盘后台] ✅ 启动成功 (每60秒扫描)"
    else
        echo "[盯盘后台] ❌ 启动失败，请检查日志: $LOG_DIR/watchdog.log"
    fi
else
    echo "[盯盘后台] ✅ 已在运行中 (PID: $WATCHDOG_PID)"
fi

echo "========================================"
echo "服务状态:"
echo "  Dashboard:  http://127.0.0.1:8891"
echo "  QMT 转发:   http://172.31.144.1:8890"
echo "  查看日志:   tail -f $LOG_DIR/{dashboard,watchdog}.log"
echo "========================================"
