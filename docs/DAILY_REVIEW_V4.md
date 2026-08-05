# v0.5 每日参与者与证据复盘

## 产品定位

系统不复制传统“资金流向”软件，也不把订单规模直接等同于投资者身份。它组合四类能力：

1. 盘面复盘结构：以开盘啦官方产品导出作为每日市场概况和短线复盘输入；
2. 席位事实层：以东方财富龙虎榜为结构化主源，以财联社授权快讯交叉核实；
3. 微观行为层：以大智慧 DDE/ACE 官方导出或授权数据描述 Level-2 订单规模行为；
4. 自动报告层：本地确定性报告为主，读取 daily_stock_analysis 和 TradingAgents-CN 的外部产物作为结构与多空观点参考。

详细接入字段和目录见 `docs/PRODUCT_SOURCES.md`。

在此基础上强制增加五项传统产品通常缺少的内容：

- 置信度；
- 替代解释；
- 历史条件概率；
- 确认与可证伪条件；
- 字段级数据来源。

## 来源边界

默认 `live`、`auto` 和 `curated` 模式使用产品源编排器：

```text
开盘啦
东方财富龙虎榜
大智慧 DDE/ACE
财联社龙虎榜
daily_stock_analysis
TradingAgents-CN
```

旧的腾讯、新浪、东方财富行情聚合、免费分笔和交易所 ETF/融资管线只在显式 `legacy` 模式中保留。产品源缺失时不会静默回退。

系统不逆向开盘啦、大智慧或财联社私有接口：

- 开盘啦读取官方产品导出；
- 东方财富龙虎榜复用 AKShare 现有适配器；
- 大智慧和财联社读取官方导出或授权端点产物；
- daily_stock_analysis 和 TradingAgents-CN 读取其生成的 Markdown/JSON，不复制其内部代码。

## 事实、计算和推断分层

### 事实

例如：

- 开盘啦导出的逐证券价格、涨跌幅和成交额；
- 东方财富整理的龙虎榜证券、上榜原因、机构次数和净额；
- 财联社授权快讯中的机构和重点席位信息；
- 大智慧导出的 DDE/ACE 订单规模字段。

### 确定性计算

例如：

- 市场上涨覆盖率；
- 市值加权收益与全市场中位数的差；
- 龙虎榜机构买卖统计；
- DDE 净额合计与覆盖成交额的比值。

### 行为假设

例如：

- 被动与配置型资金原型；
- 融资杠杆资金原型；
- 短周期交易资金原型；
- 权重配置资金原型；
- 流动性提供与套利资金原型。

行为假设不能写成账户身份。每个假设必须同时包含：

```text
activity
confidence_level
confidence_score
observation
supporting_evidence
alternative_explanations
cannot_confirm
source_fields
```

## 对手关系

对手关系描述行为类别之间可能形成的成交关系，例如：

```text
被动与配置型资金
  ↔ 现有持有人、做市和套利库存

融资杠杆资金
  ↔ 现有持有人、获利兑现或风险控制卖方

短周期主动交易资金
  ↔ 前期持有人与短期兑现资金
```

它不是对真实买卖双方的账户识别。每条关系必须带有支持证据、替代解释、确认条件和否定条件。

## 历史条件概率

系统不会把规则评分换算成概率。

历史概率来自市场历史表：

1. 使用市场宽度、全市场收益中位数、市值加权差和5日成交变化重建每日市场状态；
2. 查找与当前状态相同的历史日期；
3. 观察其后1日和5日的宽度—收益联合结果；
4. 统计三类路径频率：
   - 延续或扩散；
   - 分歧或轮动；
   - 退潮或收缩。

默认最少需要20个同状态历史样本：

```yaml
review:
  minimum_scenario_samples: 20
```

样本不足时：

```text
probability = null
probability_status = insufficient_samples
probability_source = insufficient_history
```

不得输出规则猜测的伪概率。

## 龙虎榜席位事实

`SeatFact` 保存：

```text
security_code
security_name
fact_type
buyer_labels
seller_labels
net_amount
source_id
source_date
official
limitations
```

东方财富提供结构化主记录，财联社授权产物用于快速核实。系统不会用历史“著名游资”标签填充当天事实，也不会把营业部、机构专用或交易单元等同于最终投资者。

营业部历史风格和后续表现来自东方财富近一年统计，与当天席位事实分开归档。

## 微观行为

默认微观行为层读取大智慧 DDE/ACE 导出或授权产物，生成：

- 覆盖证券数量；
- 覆盖成交额；
- DDE/大单净额合计；
- 订单规模差比率；
- 字段覆盖率。

DDE/ACE 仍然不能确认：

- 最终投资者身份；
- 真实投资意图；
- 市场资金净流入；
- 拆单后的完整母单；
- 未包含在导出中的订单和撤单行为。

旧的免费分笔采集仅在兼容工具和 `legacy` 数据链路中保留，不能冒充大智慧 DDE/ACE。

## 外部分析产物

### daily_stock_analysis

只用于参考：

- 自动日报组织；
- 定时任务和推送；
- AI 摘要表达。

其文本不参与事实字段、来源质量评分和参与者身份判断。

### TradingAgents-CN

其多空辩论摘要只进入路径的“替代解释”，不能成为：

- 对手盘身份；
- 席位事实；
- DDE 行为数据；
- 历史条件概率；
- 最终事实覆盖源。

## 字段级数据来源

`FieldProvenance` 为关键结果记录：

```text
field_path
display_name
value
unit
source_ids
evidence_level
official
as_of_date
transform
status
limitations
```

状态包括：

- `confirmed`：授权产品数据已完整导入并通过字段门槛；
- `provisional`：聚合、交叉核实或尚未完成最终确认；
- `missing`：产品导出缺失、授权不可用、字段不完整或质量门槛失败。

## 报告结构

日报按以下顺序展示：

1. 报告状态与产品来源；
2. 证据层覆盖；
3. 今日市场复盘结构；
4. 参与者原型；
5. 可能的对手关系；
6. 三条未来路径和历史条件概率；
7. 龙虎榜席位事实与 DDE/ACE 行为；
8. 板块证据矩阵；
9. 字段级数据来源；
10. 后续确认与可证伪清单；
11. 风险和限制。

## API

```text
site/api/v4/latest.json
site/api/v4/daily-review.json
site/api/v4/participant-hypotheses.json
site/api/v4/counterparty-relations.json
site/api/v4/scenario-paths.json
site/api/v4/field-provenance.json
site/api/v4/market-state.json
site/api/v4/sector-states.json
site/api/v4/source-quality.json
site/api/v4/glossary.json
```

## 下一阶段

1. 根据实际开盘啦导出样本继续扩充列名映射；
2. 增加东方财富和财联社逐条冲突检测；
3. 适配实际购买权限下的大智慧 DDE/ACE 导出模板；
4. 将 daily_stock_analysis 推送流程作为独立插件调用；
5. 对 TradingAgents-CN 产物增加长度、日期和事实引用校验；
6. 对参与者假设进行样本外校准，记录命中率和失效状态。
