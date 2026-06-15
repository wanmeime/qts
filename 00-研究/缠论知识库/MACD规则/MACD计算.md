# MACD计算

## MACD基础（第24课）

### 计算方法

- **DIF（快线）** = 12日EMA - 26日EMA
- **DEA（慢线/信号线）** = DIF的9日EMA
- **MACD柱** = 2 * (DIF - DEA)

### 图形要素

- **黄白线**：DIF和DEA两条曲线
- **红绿柱**：MACD柱状图
- **0轴**：红绿柱交界的直线
- **红柱子**：MACD为正值（DIF > DEA）
- **绿柱子**：MACD为负值（DIF < DEA）

### 参数选择

一般取12、26、9为参数，对付一般走势足够。超短线可适当调整参数。

---

## 金叉与死叉

### 金叉

DIF从下方穿越DEA向上。表示短期趋势转强。

### 死叉

DIF从上方穿越DEA向下。表示短期趋势转弱。

---

## 代码示例

```python
import numpy as np
import pandas as pd

def calculate_macd(close, fast=12, slow=26, signal=9):
    """
    计算MACD指标
    
    参数：
        close: 收盘价序列
        fast: 快线周期（默认12）
        slow: 慢线周期（默认26）
        signal: 信号线周期（默认9）
    
    返回：
        dif: 快线
        dea: 慢线/信号线
        macd: MACD柱
    """
    # 计算EMA
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    
    # 计算DIF
    dif = ema_fast - ema_slow
    
    # 计算DEA
    dea = dif.ewm(span=signal, adjust=False).mean()
    
    # 计算MACD柱
    macd = 2 * (dif - dea)
    
    return dif, dea, macd

def find_golden_cross(dif, dea):
    """
    找金叉
    """
    crosses = []
    for i in range(1, len(dif)):
        if dif[i-1] < dea[i-1] and dif[i] > dea[i]:
            crosses.append({
                'index': i,
                'type': 'golden_cross',
                'dif': dif[i],
                'dea': dea[i]
            })
    return crosses

def find_death_cross(dif, dea):
    """
    找死叉
    """
    crosses = []
    for i in range(1, len(dif)):
        if dif[i-1] > dea[i-1] and dif[i] < dea[i]:
            crosses.append({
                'index': i,
                'type': 'death_cross',
                'dif': dif[i],
                'dea': dea[i]
            })
    return crosses
```

---

## 参考章节

- 第24课：MACD基础和参数选择
