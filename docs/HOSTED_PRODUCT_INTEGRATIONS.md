# GitHub Actions 产品源真实接入

## 目标

本版本不再假设 GitHub Runner 中已经存在产品导出文件。生产流程主动执行以下步骤：

1. 读取开盘啦公开复盘页面；
2. 读取财联社公开龙虎榜专题及文章；
3. 通过 AKShare 已有函数读取东方财富全市场行情和龙虎榜；
4. 从经过授权的数据桥下载开盘啦、大智慧或财联社导出；
5. 按配置实际运行 `daily_stock_analysis`；
6. 按配置实际运行 `TradingAgents-CN`；
7. 通过发布门槛后才覆盖 `reports/latest`。

系统不会绕过登录、验证码、终端订阅或商业授权。

## 1. 开盘啦

### 自动公开层

日报 Action 会运行：

```bash
python scripts/sync_product_sources.py --date YYYY-MM-DD --root .
```

脚本遍历开盘啦公开栏目和公开文章，归档：

```text
imports/kaipanla_public/YYYY-MM-DD.json
```

包含：

- 标题和发布时间；
- 文章正文摘要；
- 原始文章地址；
- 图片地址；
- 正文中能明确提取的上涨家数、跌停家数、成交额和情绪词。

这只是开盘啦公开文章，不等同于登录后的“复盘啦”“市场情绪”或深度龙虎榜。

### 完整产品导出桥

有合法导出能力时，配置 Secrets：

```text
RADAR_KAIPANLA_EXPORT_URL
RADAR_KAIPANLA_EXPORT_TOKEN        # 可选 Bearer token
RADAR_KAIPANLA_EXPORT_SHA256       # 可选完整性校验
```

URL 可以指向用户控制的对象存储、内部网关或预签名下载地址。文件下载后写入：

```text
imports/kaipanla/YYYY-MM-DD.<ext>
```

完整产品导出优先于公开文章；公开文章仍作为文本背景保留。

## 2. 东方财富

无需另建爬虫。生产 Provider 复用 AKShare 已有函数：

```text
stock_zh_a_spot_em
stock_lhb_detail_em
stock_lhb_jgmmtj_em
stock_lhb_hyyyb_em
stock_lhb_yybph_em
stock_lhb_traderstatistic_em
```

用途：

- A股全市场快照和市场宽度；
- 当日龙虎榜；
- 机构买卖统计；
- 活跃营业部；
- 营业部历史后续表现和交易统计。

生产发布门槛要求东方财富市场快照至少覆盖 4,000 只证券、日期一致、schema 有效且市场状态不是“数据不足”。

## 3. 财联社

### 自动公开层

同步脚本读取财联社龙虎榜专题和公开详情页，归档：

```text
imports/cls/YYYY-MM-DD.csv
```

可提取字段包括：

- 标题和正文摘要；
- 发布时间；
- 明确披露的证券代码和名称；
- 机构或重点席位标签；
- 明确披露的净买卖金额；
- 原始文章地址。

文章没有证券代码时不会猜测代码。财联社只用于交叉核实，不覆盖东方财富结构化龙虎榜。

### 授权导出桥

可选 Secrets：

```text
RADAR_CLS_LHB_EXPORT_URL
RADAR_CLS_LHB_EXPORT_TOKEN
RADAR_CLS_LHB_EXPORT_SHA256
```

授权文件会覆盖同名日期导入文件，公开文章仍保留在同步诊断中。

## 4. 大智慧 DDE/ACE

大智慧 DDE/ACE 来自付费 Level-2 产品，GitHub 托管 Ubuntu Runner 无法合法生成。仓库提供两段真实链路。

### A. 自托管 Windows Runner 导出桥

工作流：

```text
.github/workflows/dazhihui_export_bridge.yml
```

Runner 标签：

```text
self-hosted, Windows, X64, dazhihui
```

该 Runner 必须安装用户合法授权的大智慧终端，并能生成 CSV、Excel 或 JSON 导出。

Repository variables：

```text
RADAR_ENABLE_DAZHIHUI_BRIDGE=true
RADAR_DAZHIHUI_EXPORT_PATH=C:\Radar\exports\dde-{date}.csv
RADAR_DAZHIHUI_EXPORT_SCRIPT=C:\Radar\export-dazhihui.ps1   # 可选
RADAR_DAZHIHUI_UPLOAD_METHOD=PUT
```

导出脚本契约：

```powershell
param(
  [string]$TradeDate,
  [string]$OutputPath
)
```

Secrets：

```text
RADAR_DAZHIHUI_UPLOAD_URL
RADAR_DAZHIHUI_UPLOAD_TOKEN
```

桥接工作流会验证导出包含 DDE/大单净额和成交额字段，计算 SHA256 后上传。

### B. 日报 Runner 下载

日报工作流配置：

```text
RADAR_DAZHIHUI_DDE_EXPORT_URL
RADAR_DAZHIHUI_DDE_EXPORT_TOKEN
RADAR_DAZHIHUI_DDE_EXPORT_SHA256
```

下载后的文件进入：

```text
imports/dazhihui/YYYY-MM-DD.<ext>
```

哈希、schema 或字段不合格时，大智慧证据层保持缺失；不会用免费分笔冒充 DDE/ACE。

## 5. daily_stock_analysis

默认关闭，避免在没有模型密钥时产生假成功或无意义报告。

Repository variables：

```text
RADAR_ENABLE_DAILY_STOCK_ANALYSIS=true
RADAR_ANALYSIS_SYMBOLS=600519,000001
RADAR_DSA_REF=ed848da6f0fc1080e1a61a1799b9c7d510a3eaca
RADAR_DSA_COMMAND=main.py --market-review --no-notify --force-run
```

至少配置该项目支持的一组模型密钥，例如：

```text
ANSPIRE_API_KEYS
AIHUBMIX_KEY
OPENAI_API_KEY
GEMINI_API_KEY
```

Action 会：

1. 克隆固定 commit；
2. 创建隔离虚拟环境；
3. 安装上游 requirements；
4. 运行上游 `main.py --market-review`；
5. 优先保存上游实际生成的 Markdown/JSON；
6. 找不到报告文件时保存完整进程输出；
7. 将产物写入 `imports/daily_stock_analysis/YYYY-MM-DD.md`。

它只进入自动报告层，不进入市场事实和席位事实。

## 6. TradingAgents-CN

默认关闭。启用前应确认上游许可证适用于实际使用场景。

Repository variables：

```text
RADAR_ENABLE_TRADINGAGENTS_CN=true
RADAR_TRADINGAGENTS_SYMBOLS=600519,000001
RADAR_TRADINGAGENTS_REF=74783e8817d6cf6de29867880631cc555153f36b
RADAR_TRADINGAGENTS_PROVIDER=openai
RADAR_TRADINGAGENTS_DEEP_MODEL=gpt-4o-mini
RADAR_TRADINGAGENTS_QUICK_MODEL=gpt-4o-mini
```

根据 Provider 配置模型和数据密钥，例如：

```text
OPENAI_API_KEY
DASHSCOPE_API_KEY
DEEPSEEK_API_KEY
FINNHUB_API_KEY
TUSHARE_TOKEN
```

Action 会克隆固定 commit、创建隔离环境，通过上游 `TradingAgentsGraph` 实际运行所配置证券，并保存：

```text
imports/tradingagents_cn/YYYY-MM-DD.json
```

该结果只能进入路径的替代解释和多空辩论，不会成为交易者身份、龙虎榜事实或历史概率输入。

## 7. 失败与严格模式

公开源、授权下载和外部项目的诊断分别写入：

```text
diagnostics/product_source_sync.json
diagnostics/external_analyses.json
diagnostics/dazhihui_publish.json
```

外部 AI 默认是可选增强。开启以下变量后，任何已启用外部项目失败都会阻断日报：

```text
RADAR_EXTERNAL_ANALYSES_STRICT=true
```

无论外部 AI 是否启用，市场发布门槛始终生效。市场快照不完整、日期不一致或当日 confirmed 运行过早时，旧的有效 `reports/latest` 会被保留。

## 8. 安全边界

- 不把账户 Cookie、密码或终端许可证写入仓库；
- 授权产物通过 GitHub Secrets、Bearer token、预签名 URL 和 SHA256 传递；
- 外部项目固定 commit，避免每天无审查地执行上游最新代码；
- 外部项目运行在独立虚拟环境；
- 原始产物只上传为有限保留期的 Action artifact，不提交到 Git 历史；
- 任何产品标签都不等于最终投资者身份。
