# Two-Year Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend backtest interval from 6 months to 2 years, download 2 years of data, and run the highest-yield 缠论 strategy to validate stability.

**Architecture:** 
1. Modify data download script to fetch 2 years of K-line data (replace 6-month cache)
2. Modify backtest.py to use 2-year interval (730 days)
3. Run backtest and analyze results

**Tech Stack:** Python, akshare, pandas, multiprocessing

---

### Task 1: Modify Data Download Script for 2-Year Data

**Covers:** Data download for 2-year backtest

**Files:**
- Modify: `/home/jiaod/qts/00-研究/数据源/拉取半年K线.py`

- [ ] **Step 1: Update date range in download script**

Change the date range from 6 months to 2 years:

```python
# Original (lines 49-54):
df = ak.stock_zh_a_hist_tx(
    symbol=code,
    start_date="20251201",
    end_date="20260602",
    adjust="qfq"
)

# New (2-year range: 2024-06-20 to 2026-06-20):
df = ak.stock_zh_a_hist_tx(
    symbol=code,
    start_date="20240620",
    end_date="20260620",
    adjust="qfq"
)
```

- [ ] **Step 2: Update cache directory name**

```python
# Original (line 17):
CACHE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_6m"

# New:
CACHE_DIR = "/home/jiaod/qts/00-研究/数据源/缓存/kline_2y"
```

- [ ] **Step 3: Update script description**

```python
# Original (lines 1-5):
"""
拉取全A股半年K线数据（腾讯源）+ 行业分类（同花顺）
输出：qts/00-研究/数据源/缓存/kline_6m/
"""

# New:
"""
拉取全A股2年K线数据（腾讯源）+ 行业分类（同花顺）
输出：qts/00-研究/数据源/缓存/kline_2y/
"""
```

- [ ] **Step 4: Commit changes**

```bash
cd /home/jiaod/qts
git add 00-研究/数据源/拉取半年K线.py
git commit -m "feat: update data download script for 2-year interval"
```

---

### Task 2: Update Backtest Script for 2-Year Interval

**Covers:** Backtest configuration for 2-year interval

**Files:**
- Modify: `/home/jiaod/qts/20-回测/盯盘策略回测/backtest.py`

- [ ] **Step 1: Update KLINE_CACHE_DIR path**

```python
# Original (line 45):
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_6m"

# New:
KLINE_CACHE_DIR = PROJECT_ROOT / "00-研究" / "数据源" / "缓存" / "kline_2y"
```

- [ ] **Step 2: Update BACKTEST_START to 2 years**

```python
# Original (line 64):
BACKTEST_START = BACKTEST_END - timedelta(days=180)

# New (730 days = 2 years):
BACKTEST_START = BACKTEST_END - timedelta(days=730)
```

- [ ] **Step 3: Update CACHE_VERSION to invalidate old cache**

```python
# Original (line 50):
CACHE_VERSION = 2

# New:
CACHE_VERSION = 3
```

- [ ] **Step 4: Update help text for --days argument**

```python
# Original (line 1053):
parser.add_argument("--days", type=int, default=180,
                    help="回测天数（默认180天）")

# New:
parser.add_argument("--days", type=int, default=730,
                    help="回测天数（默认730天=2年）")
```

- [ ] **Step 5: Commit changes**

```bash
cd /home/jiaod/qts
git add 20-回测/盯盘策略回测/backtest.py
git commit -m "feat: update backtest to 2-year interval"
```

---

### Task 3: Download 2-Year Data

**Covers:** Data acquisition for 2-year backtest

**Files:**
- Run: `/home/jiaod/qts/00-研究/数据源/拉取半年K线.py`

- [ ] **Step 1: Run data download script**

```bash
cd /home/jiaod/qts
python3 00-研究/数据源/拉取半年K线.py
```

Expected output:
- Script will download ~5000 stocks × 2 years of daily K-line data
- Estimated time: ~1-2 hours depending on network speed
- Data saved to `00-研究/数据源/缓存/kline_2y/`

- [ ] **Step 2: Verify data download**

```bash
# Check number of files downloaded
ls /home/jiaod/qts/00-研究/数据源/缓存/kline_2y/ | wc -l

# Check file size (should be larger than 6-month data)
du -sh /home/jiaod/qts/00-研究/数据源/缓存/kline_2y/
```

Expected: ~5000 CSV files, total size ~200-300MB

---

### Task 4: Run 2-Year Backtest

**Covers:** Execute backtest with 2-year interval

**Files:**
- Run: `/home/jiaod/qts/20-回测/盯盘策略回测/backtest.py`

- [ ] **Step 1: Run backtest**

```bash
cd /home/jiaod/qts
python3 20-回测/盯盘策略回测/backtest.py
```

Expected output:
- Strategy: 缠论底分型/顶分型确认买卖（多仓版）
- Interval: 2024-06-20 ~ 2026-06-20 (2 years)
- Initial capital: ¥10,000
- Results saved to `20-回测/盯盘策略回测/回测结果_YYYYMMDD_HHMM/`

- [ ] **Step 2: Review backtest results**

Check the generated report for:
- Total return percentage
- Sharpe ratio
- Max drawdown
- Win rate
- Number of trades (should be more than 24 from 6-month test)

- [ ] **Step 3: Compare with 6-month results**

Compare key metrics:
- 6-month result: 34.61% return, 24 trades, Sharpe 1.58
- 2-year result: TBD

---

### Task 5: Analysis and Documentation

**Covers:** Validate strategy stability over 2-year period

**Files:**
- Create: `/home/jiaod/qts/20-回测/盯盘策略回测/2year_backtest_analysis.md`

- [ ] **Step 1: Document 2-year backtest results**

Create analysis document with:
- Performance comparison (6-month vs 2-year)
- Monthly return breakdown
- Key observations about strategy stability
- Recommendations

- [ ] **Step 2: Update project memory**

Record key findings in memory for future reference.

---

## Execution Notes

1. **Data download will take time**: ~1-2 hours for 5000 stocks
2. **Backtest will be slower**: More data = more processing time
3. **Cache invalidation**: CACHE_VERSION bump ensures fresh analysis
4. **Parallel processing**: NUM_WORKERS=14 for faster analysis

## Success Criteria

- [ ] 2-year data downloaded successfully (~5000 stocks)
- [ ] Backtest completes without errors
- [ ] Results show >50 trades (statistically significant)
- [ ] Performance metrics documented and compared
