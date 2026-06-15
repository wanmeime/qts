# AKShare 数据源配置

## 基本信息
- 包名：akshare
- 版本：1.18.64
- 安装路径：~/.local/lib/python3.12/site-packages/akshare
- 无需API Key，完全免费

## 常用接口

### 宏观经济
| 函数 | 数据 | 频率 |
|------|------|------|
| `ak.macro_china_cpi()` | 中国CPI | 月度 |
| `ak.macro_china_pmi()` | 中国PMI | 月度 |
| `ak.macro_china_shibor()` | Shibor利率 | 日度 |
| `ak.macro_china_gdp()` | GDP | 季度 |
| `ak.macro_china_lpr()` | LPR利率 | 月度 |

### A股行情
| 函数 | 数据 | 说明 |
|------|------|------|
| `ak.stock_zh_a_spot_em()` | A股实时行情 | 全市场快照 |
| `ak.stock_zh_a_hist()` | 个股历史K线 | 按股票代码 |
| `ak.stock_zh_a_hist_min_em()` | 分钟级K线 | 日内数据 |
| `ak.stock_board_industry_name_em()` | 行业板块列表 | 行业分类 |
| `ak.stock_board_industry_hist_em()` | 行业板块K线 | 行业指数 |

### 财务数据
| 函数 | 数据 | 说明 |
|------|------|------|
| `ak.stock_financial_abstract()` | 财务摘要 | 按股票代码 |
| `ak.stock_financial_report_sina()` | 三大报表 | 资产负债/利润/现金流 |

## 注意事项
- akshare接口可能因网站变动而更新，遇到报错先 `pip install -U akshare`
- 拉取全量数据时注意限流，加 `time.sleep(1)` 间隔
- 大量数据建议缓存到 `缓存/` 目录，避免重复拉取
