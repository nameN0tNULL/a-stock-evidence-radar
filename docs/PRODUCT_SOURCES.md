# 产品数据源接入规范

## 当前生产架构

`live`、`auto` 和 `curated` 使用可在 GitHub Actions 中运行的产品源组合：

| 来源 | 自动方式 | 事实角色 |
|---|---|---|
| 开盘啦 | 读取公开复盘文章；完整产品数据可通过授权导出 URL 下载 | 复盘背景和产品口径 |
| 东方财富 | 复用 AKShare 全市场快照和龙虎榜函数 | 结构化市场与龙虎榜主源 |
| 大智慧 DDE/ACE | 自托管授权 Windows 终端导出，再由日报 Runner 下载 | Level-2 订单规模行为 |
| 财联社 | 读取公开龙虎榜专题和详情页；也支持授权导出 | 龙虎榜新闻交叉核实 |
| daily_stock_analysis | 克隆固定 commit，在隔离环境实际运行 | 自动日报结构，非事实源 |
| TradingAgents-CN | 克隆固定 commit，通过 `TradingAgentsGraph` 实际运行 | 多空替代解释，非事实源 |

具体 GitHub Variables、Secrets、自托管 Runner 和运行命令见：

```text
docs/HOSTED_PRODUCT_INTEGRATIONS.md
```

## 运行模式

```bash
a-stock-radar run --date 2026-08-06 --data-mode auto
```

模式含义：

- `auto/live/curated`：使用托管产品源组合；
- `legacy`：显式使用旧的免费兼容源；
- `mock`：演示数据，不允许覆盖生产日报。

产品源失败时不会用 mock 数据补齐。市场快照不完整时，发布门槛会阻止覆盖上一份有效报告。

## 开盘啦

公开层归档：

```text
imports/kaipanla_public/YYYY-MM-DD.json
```

授权导出归档：

```text
imports/kaipanla/YYYY-MM-DD.<csv|xlsx|json>
```

完整导出的最小字段：

```text
代码 / security_code
名称 / security_name
最新价 / close
涨跌幅 / pct_change
成交额 / amount
```

公开文章不等同于登录态内的完整“复盘啦”、市场情绪或深度龙虎榜。

## 东方财富

使用现成 AKShare 适配器：

```text
stock_zh_a_spot_em
stock_lhb_detail_em
stock_lhb_jgmmtj_em
stock_lhb_hyyyb_em
stock_lhb_yybph_em
stock_lhb_traderstatistic_em
```

归档包括全市场快照、龙虎榜、机构统计、活跃营业部和历史后续表现。营业部、机构专用或交易单元不等于最终投资者。

## 大智慧 DDE/ACE

GitHub 托管 Ubuntu Runner 不会绕过大智慧授权或伪造 DDE。真实链路是：

```text
已授权大智慧 Windows 终端
  -> 用户拥有的导出脚本
  -> self-hosted Windows Runner
  -> 带 SHA256 的对象存储/内部网关
  -> 日报 Runner 下载并校验
  -> DDE/ACE 标准化
```

最小字段：

```text
DDE净额 / 大单净额 / dde_net_amount
成交额 / 成交金额 / amount
```

订单规模差是产品口径，不是市场净流入，也不能识别最终账户。

## 财联社

公开层读取龙虎榜专题和公开详情页，归档：

```text
imports/cls/YYYY-MM-DD.csv
```

可核实字段包括标题、发布时间、明确披露的证券代码、席位标签、净买卖金额和原文地址。没有披露代码时不猜测。

东方财富是结构化主源，财联社是交叉核实源；冲突时保留双方来源，不静默覆盖。

## 外部开源分析项目

实际运行脚本：

```text
scripts/run_external_analyses.py
```

产物：

```text
imports/daily_stock_analysis/YYYY-MM-DD.md
imports/tradingagents_cn/YYYY-MM-DD.json
```

两个项目都固定上游 commit，并在独立虚拟环境运行。它们不会参与市场成交额、龙虎榜席位、DDE 或历史条件概率计算。

## 原始归档

每次生产运行写入：

```text
data/raw/product_sources/date=YYYYMMDD/
```

主要产物：

```text
eastmoney_market_snapshot.csv
kaipanla_public_review.json
kaipanla_export.csv
eastmoney_lhb_*.csv
cls_lhb_authorized.csv
dazhihui_dde_ace.csv
seat_facts.json
dde_summary.json
external_analyses.json
manifest.json
```

## 冲突与优先级

1. 东方财富全市场快照负责可计算的市场宽度；
2. 开盘啦提供复盘结构和产品叙事，不覆盖结构化市场事实；
3. 东方财富负责结构化龙虎榜，财联社负责交叉核实；
4. 大智慧只接受授权终端产物；
5. 外部 AI 文本与结构化事实冲突时，以结构化事实为准；
6. 每个字段必须保留来源、日期、转换方式、证据等级和限制。
