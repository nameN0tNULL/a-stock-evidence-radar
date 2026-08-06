# 产品数据源接入规范

## 目标

默认 `live` 模式只使用下列指定来源：

| 来源 | 在系统中的职责 | 接入方式 | 是否作为事实源 |
|---|---|---|---|
| 开盘啦 | 每日市场概况、短线复盘结构 | 官方产品导出文件 | 是，按产品口径标记为 L2 |
| 东方财富龙虎榜 | 当日龙虎榜、机构统计、活跃营业部、营业部历史后续表现 | 复用 AKShare 已有东方财富适配器 | 是，标记为 L2/L3 |
| 大智慧 DDE/ACE | Level-2 订单规模和大单行为 | 官方导出或授权接口产物 | 是，标记为 L3 |
| 财联社龙虎榜 | 当日机构和重点席位快讯交叉核实 | 授权导出或授权端点产物 | 是，标记为 L2 |
| daily_stock_analysis | 自动日报、推送和 AI 摘要架构 | 读取该项目生成的 Markdown/JSON 产物 | 否，标记为 L4 |
| TradingAgents-CN | 多空观点和替代解释参考 | 读取该项目生成的 Markdown/JSON 产物 | 否，标记为 L4 |

系统不逆向开盘啦、大智慧或财联社的私有接口，不复制两个开源项目的内部实现。缺少官方导出、授权端点或外部分析产物时，相应证据层保持 `missing` 或 `partial`。

## 运行模式

```bash
a-stock-radar run --date 2026-07-31 --data-mode live
```

`live`、`auto` 和 `curated` 都使用产品源编排器。

旧的腾讯、新浪、东方财富行情聚合与交易所 ETF/融资管线仅在显式兼容模式下运行：

```bash
a-stock-radar run --date 2026-07-31 --data-mode legacy
```

产品源缺失时，默认模式不会静默回退到旧行情抓取。

## 文件发现规则

每个产品可通过环境变量指定完整路径，也可放入默认目录。文件名支持：

```text
YYYY-MM-DD.csv
YYYYMMDD.csv
YYYY-MM-DD.json
YYYYMMDD.json
YYYY-MM-DD.xlsx
YYYY-MM-DD.md
```

环境变量中的路径可以使用占位符：

```text
{date}          -> 2026-07-31
{compact_date}  -> 20260731
```

例如：

```bash
export RADAR_KAIPANLA_EXPORT=/exports/kpl/{date}.xlsx
export RADAR_DAZHIHUI_DDE_EXPORT=/exports/dzh/{compact_date}.csv
```

## 开盘啦

### 默认目录

```text
imports/kaipanla/
```

### 环境变量

```text
RADAR_KAIPANLA_EXPORT
```

### 最小字段

以下每组别名至少需要一个：

| 标准字段 | 可接受别名 |
|---|---|
| `security_code` | `代码`、`股票代码`、`证券代码`、`code`、`symbol` |
| `security_name` | `名称`、`股票简称`、`证券简称`、`name` |
| `close` | `最新价`、`收盘价`、`现价`、`close` |
| `pct_change` | `涨跌幅`、`涨幅`、`change_rate` |
| `amount` | `成交额`、`成交金额`、`turnover` |

可选字段：

```text
流通市值 / float_market_cap
换手率 / turnover_rate
```

金额支持元、万、亿和万亿后缀。股票代码按字符串读取，避免前导零丢失。

开盘啦导出是默认市场复盘数据。缺失时市场复盘层保持缺失，不以腾讯或新浪补齐。

## 东方财富龙虎榜

无需本地导出，直接复用 AKShare 中现成的东方财富函数：

```text
stock_lhb_detail_em
stock_lhb_jgmmtj_em
stock_lhb_hyyyb_em
stock_lhb_yybph_em
stock_lhb_traderstatistic_em
```

分别用于：

- 当日龙虎榜详情和上榜后收益字段；
- 机构买卖每日统计；
- 每日活跃营业部；
- 营业部近一年后续表现；
- 营业部近一年交易统计。

输出会保存至：

```text
data/raw/product_sources/date=YYYYMMDD/eastmoney_*.csv
```

席位事实只保留证券、上榜原因、机构专用次数、净额和来源等可核实字段。营业部、机构专用和交易单元不等于最终投资者。

## 大智慧 DDE/ACE

### 默认目录

```text
imports/dazhihui/
```

### 环境变量

```text
RADAR_DAZHIHUI_DDE_EXPORT
```

### 最小字段

订单规模差字段至少一个：

```text
DDE净额
大单净额
超大单净额
主力净额
dde_net_amount
```

成交额字段至少一个：

```text
成交额
成交金额
amount
turnover
```

系统计算：

```text
订单规模差比率 = 导出中 DDE 净额合计 / 对应成交额合计
```

该指标是大智慧产品口径下的订单规模行为，不是市场净流入，也不能识别机构、游资、量化或个人账户。

## 财联社龙虎榜

### 默认目录

```text
imports/cls/
```

### 环境变量

```text
RADAR_CLS_LHB_EXPORT
```

### 推荐字段

```text
代码 / security_code
名称 / security_name
标题 / title
买方席位 / buyer_labels
卖方席位 / seller_labels
净买额 / net_amount
```

财联社数据只用于快速交叉核实。东方财富和财联社出现冲突时，系统保留冲突并要求人工核对，不自动覆盖。

## daily_stock_analysis

### 默认目录

```text
imports/daily_stock_analysis/
```

### 环境变量

```text
RADAR_DAILY_STOCK_ANALYSIS_ARTIFACT
```

支持 Markdown、文本或 JSON 产物。JSON 会优先读取：

```text
summary
market_review
analysis
decision
report
```

该产物只用于参考日报编排、推送摘要和表达结构，不参与事实字段、来源质量评分或参与者身份判断。

## TradingAgents-CN

### 默认目录

```text
imports/tradingagents_cn/
```

### 环境变量

```text
RADAR_TRADINGAGENTS_CN_ARTIFACT
```

支持 Markdown、文本或 JSON 产物。其多空辩论摘要只进入场景路径的“替代解释”，不能成为席位事实、对手盘身份或历史概率的输入。

## 归档产物

每次运行写入：

```text
data/raw/product_sources/date=YYYYMMDD/
```

主要文件：

```text
kaipanla_export.csv
eastmoney_lhb_detail.csv
eastmoney_lhb_institution.csv
eastmoney_lhb_active_departments.csv
eastmoney_department_followup.csv
eastmoney_department_style.csv
cls_lhb_authorized.csv
dazhihui_dde_ace.csv
seat_facts.json
dde_summary.json
external_analyses.json
manifest.json
```

`manifest.json` 记录每个来源是否可用、行数、级别、错误和本次编排规则。

## 来源优先级和冲突规则

1. 开盘啦只负责市场复盘结构，不覆盖龙虎榜或 DDE。
2. 东方财富是龙虎榜结构化主源。
3. 财联社是龙虎榜快讯交叉核实源，不静默覆盖东方财富。
4. 大智慧是微观订单规模行为源，不用免费分笔抓取冒充 DDE/ACE。
5. daily_stock_analysis 和 TradingAgents-CN 永远是分析产物，不是市场事实。
6. 外部 AI 文本与结构化数据冲突时，以结构化数据为准。
7. 所有产品字段仍需保留来源、日期、转换方式、置信度和限制说明。
