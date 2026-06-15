#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QTS 90-复盘层 - 参数优化记录模块
功能：
  1. 记录每次策略参数变更
  2. 追踪参数版本历史
  3. 对比不同参数版本的表现
  4. 生成参数优化建议
"""

import json
import os
import sys
import hashlib
from datetime import datetime
from pathlib import Path


# ========== 配置 ==========
BASE_DIR = Path("/home/jiaod/qts")
回测目录 = BASE_DIR / "20-回测"
参数优化目录 = BASE_DIR / "90-复盘/参数优化"
参数历史文件 = 参数优化目录 / "参数版本历史.json"


def 读取JSON(路径):
    """读取JSON文件"""
    with open(路径, 'r', encoding='utf-8') as f:
        return json.load(f)


def 保存JSON(路径, 数据):
    """保存JSON文件"""
    os.makedirs(os.path.dirname(路径), exist_ok=True)
    with open(路径, 'w', encoding='utf-8') as f:
        json.dump(数据, f, ensure_ascii=False, indent=2)


def 计算参数指纹(参数字典):
    """计算参数的唯一指纹，用于判断参数是否变更"""
    参数字符串 = json.dumps(参数字典, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(参数字符串.encode()).hexdigest()[:8]


def 加载参数历史():
    """加载参数版本历史"""
    if 参数历史文件.exists():
        return 读取JSON(参数历史文件)
    return {"版本列表": [], "当前版本": {}}


def 保存参数历史(历史):
    """保存参数版本历史"""
    保存JSON(参数历史文件, 历史)


def 注册策略参数(策略名, 参数字典, 版本标签="", 备注=""):
    """
    注册/更新策略参数
    如果参数有变化则创建新版本
    """
    历史 = 加载参数历史()
    指纹 = 计算参数指纹(参数字典)
    
    # 检查是否已存在相同参数
    当前版本 = 历史.get("当前版本", {})
    if 策略名 in 当前版本 and 当前版本[策略名].get("指纹") == 指纹:
        print(f"ℹ️ {策略名} 参数未变更，跳过注册")
        return 当前版本[策略名]
    
    # 创建新版本记录
    版本号 = len([v for v in 历史["版本列表"] if v["策略名"] == 策略名]) + 1
    版本记录 = {
        "策略名": 策略名,
        "版本号": f"v{版本号}",
        "版本标签": 版本标签 or f"{策略名}-v{版本号}",
        "指纹": 指纹,
        "参数": 参数字典,
        "注册时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "备注": 备注,
        "回测指标": {},
        "实盘指标": {}
    }
    
    历史["版本列表"].append(版本记录)
    if "当前版本" not in 历史:
        历史["当前版本"] = {}
    历史["当前版本"][策略名] = 版本记录
    
    保存参数历史(历史)
    print(f"✅ {策略名} 参数版本 {版本记录['版本号']} 已注册 (指纹: {指纹})")
    return 版本记录


def 关联回测指标(策略名, 版本标签, 回测指标):
    """将回测指标关联到参数版本"""
    历史 = 加载参数历史()
    
    for 版本 in 历史["版本列表"]:
        if 版本["策略名"] == 策略名 and 版本["版本标签"] == 版本标签:
            版本["回测指标"] = 回测指标
            保存参数历史(历史)
            print(f"✅ 回测指标已关联到 {策略名} {版本标签}")
            return True
    
    print(f"⚠️ 未找到 {策略名} {版本标签}")
    return False


def 关联实盘指标(策略名, 日期字符串, 实盘指标):
    """将实盘指标关联到当前参数版本"""
    历史 = 加载参数历史()
    当前版本 = 历史.get("当前版本", {}).get(策略名)
    
    if not 当前版本:
        print(f"⚠️ {策略名} 未注册当前参数版本")
        return False
    
    # 追加实盘指标到时间序列
    if "实盘指标" not in 当前版本:
        当前版本["实盘指标"] = {}
    当前版本["实盘指标"][日期字符串] = 实盘指标
    
    # 同步更新版本列表中的记录
    for 版本 in 历史["版本列表"]:
        if 版本["指纹"] == 当前版本["指纹"]:
            版本["实盘指标"] = 当前版本["实盘指标"]
    
    保存参数历史(历史)
    return True


def 从回测自动注册():
    """从回测目录自动注册已有的策略参数"""
    动量路径 = 回测目录 / "动量轮动策略/20260602-v1/指标.json"
    多因子路径 = 回测目录 / "多因子选股策略/20260602-v1/回测指标.json"
    
    结果 = []
    
    # 动量轮动策略
    if 动量路径.exists():
        data = 读取JSON(动量路径)
        参数 = data.get("参数", {})
        绩效 = data.get("绩效指标", {})
        
        版本 = 注册策略参数(
            "动量轮动",
            参数,
            版本标签="20260602-v1",
            备注="初始版本-动量回看5天持仓5天"
        )
        关联回测指标("动量轮动", "20260602-v1", 绩效)
        结果.append(("动量轮动", 版本))
    
    # 多因子选股策略
    if 多因子路径.exists():
        data = 读取JSON(多因子路径)
        
        参数 = {
            "调仓频率": "每月初",
            "持仓数量": 10,
            "配置方式": "等权",
            "因子权重": {
                "PE": 0.20,
                "PB": 0.15,
                "换手率": 0.15,
                "总市值": 0.20,
                "成交额": 0.15,
                "涨跌幅": 0.15
            }
        }
        
        绩效 = {
            "总收益率": f"{data.get('total_return', 0)*100:.2f}%",
            "年化收益率": f"{data.get('annual_return', 0)*100:.2f}%",
            "夏普比率": round(data.get("sharpe_ratio", 0), 4),
            "最大回撤": f"{data.get('max_drawdown', 0)*100:.2f}%",
            "Calmar比率": round(data.get("calmar_ratio", 0), 4),
            "年化波动率": f"{data.get('volatility', 0)*100:.2f}%"
        }
        
        版本 = 注册策略参数(
            "多因子选股",
            参数,
            版本标签="20260602-v1",
            备注="初始版本-等权6因子月度调仓"
        )
        关联回测指标("多因子选股", "20260602-v1", 绩效)
        结果.append(("多因子选股", 版本))
    
    return 结果


def 生成参数对比报告():
    """生成参数版本对比报告"""
    历史 = 加载参数历史()
    
    if not 历史["版本列表"]:
        return "暂无参数版本记录"
    
    lines = []
    lines.append("### 参数版本历史")
    lines.append("")
    
    # 按策略分组
    策略分组 = {}
    for 版本 in 历史["版本列表"]:
        策略名 = 版本["策略名"]
        if 策略名 not in 策略分组:
            策略分组[策略名] = []
        策略分组[策略名].append(版本)
    
    for 策略名, 版本列表 in 策略分组.items():
        lines.append(f"#### {策略名}")
        lines.append("")
        
        # 当前版本
        当前 = 历史.get("当前版本", {}).get(策略名)
        if 当前:
            lines.append(f"**当前版本**: {当前['版本号']} ({当前['版本标签']})")
            lines.append("")
            
            # 参数详情
            lines.append("参数:")
            for k, v in 当前["参数"].items():
                if isinstance(v, dict):
                    lines.append(f"  - {k}:")
                    for kk, vv in v.items():
                        lines.append(f"    - {kk}: {vv}")
                else:
                    lines.append(f"  - {k}: {v}")
            lines.append("")
            
            # 回测指标
            if 当前.get("回测指标"):
                lines.append("回测指标:")
                for k, v in 当前["回测指标"].items():
                    lines.append(f"  - {k}: {v}")
                lines.append("")
        
        # 版本历史
        if len(版本列表) > 1:
            lines.append("历史版本:")
            for v in 版本列表[:-1]:
                lines.append(f"  - {v['版本号']} ({v['注册时间']}): {v.get('备注', '无')}")
            lines.append("")
    
    return "\n".join(lines)


def 生成参数优化Markdown():
    """生成参数优化记录的Markdown片段"""
    lines = []
    lines.append("## 六、参数优化记录")
    lines.append("")
    lines.append(生成参数对比报告())
    return "\n".join(lines)


if __name__ == "__main__":
    print("🔧 QTS参数优化记录管理")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] == "注册":
        # 从回测自动注册
        结果 = 从回测自动注册()
        for 策略名, 版本 in 结果:
            print(f"✅ {策略名} -> {版本['版本号']} (指纹: {版本['指纹']})")
    elif len(sys.argv) > 1 and sys.argv[1] == "报告":
        # 生成对比报告
        print(生成参数对比报告())
    else:
        # 默认：自动注册
        结果 = 从回测自动注册()
        for 策略名, 版本 in 结果:
            print(f"✅ {策略名} -> {版本['版本号']}")
        print(f"\n历史版本数: {len(加载参数历史()['版本列表'])}")
