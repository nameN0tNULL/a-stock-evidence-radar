# v0.4 每日参与者与证据复盘

## 产品定位

v0.4 不复制传统“资金流向”软件，也不把订单规模直接等同于投资者身份。它组合四类能力：

1. 盘面复盘结构：市场宽度、收益中位数、权重差、成交变化和板块扩散；
2. 席位事实层：预留龙虎榜、机构专用、营业部和交易单元事实模型；
3. 微观行为层：免费分笔成交或未来完整 Level-2 所能支持的行为指标；
4. 自动报告层：每天生成结构化 JSON、Markdown 和 HTML。

在此基础上强制增加五项传统产品通常缺少的内容：

- 置信度；
- 替代解释；
- 历史条件概率；
- 确认与可证伪条件；
- 字段级数据来源。

## 事实、计算和推断分层

### 事实

例如：

- 交易所披露的融资余额；
- 基金日终份额；
- 龙虎榜中的营业部或交易单元；
- 逐证券成交额和涨跌幅。

### 确定性计算

例如：

- 市场上涨覆盖率；
- 市值加权收益与全市场中位数的差；
- ETF份额变化乘以净值代理；
- 融资余额5日变化率。

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

历史条件概率描述样本频率，不代表因果关系。市场制度、数据来源和交易成本变化可能使历史关系失效。

## 龙虎榜席位事实

数据模型已经预留 `SeatFact`：

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

当前生产管线尚未接入龙虎榜，因此：

```text
seat_facts = []
seat_facts layer status = missing
```

系统不会用历史游资标签填充当天事实。后续接入时仍必须保留两条限制：

- 营业部或交易单元不等于最终投资者；
- 历史席位标签不能证明当天账户身份。

## 微观行为

系统会读取：

```text
data/raw/tick_trade/date=YYYYMMDD/code=*/manifest.json
```

只聚合没有被质量门槛拒绝的证券，生成：

- 覆盖证券数量；
- 已完成日终成交额核验的证券数量；
- 暂定证券数量；
- 分笔成交总额；
- 供应方标记成交金额失衡；
- 买卖方向分类覆盖率；
- 14:57以后成交额占比。

普通分笔成交仍然不能支持：

- 真实订单流失衡；
- 撤单失衡；
- 订单存活时间；
- 完整订单簿重建；
- 具体交易者身份。

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

- `confirmed`：正式来源或完成核验；
- `provisional`：结构化聚合或尚未完成官方总量核验；
- `missing`：字段缺失、历史不连续或质量门槛失败。

低等级数据只能补缺，不能无提示覆盖高等级事实。

## 报告结构

v0.4 日报按以下顺序展示：

1. 报告状态与数据源；
2. 证据层覆盖；
3. 今日市场复盘结构；
4. 参与者原型；
5. 可能的对手关系；
6. 三条未来路径和历史条件概率；
7. 龙虎榜席位事实与微观行为；
8. 板块证据矩阵；
9. 字段级数据来源；
10. 后续确认与可证伪清单；
11. 风险和限制。

## API

v0.4 新增：

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

为避免已有调用立即失效，v3核心端点暂时继续写入。

## 下一阶段

优先级如下：

1. 接入交易所龙虎榜和东方财富营业部统计，先记录事实，不做身份确认；
2. 建立营业部历史行为统计，并将历史标签与当天席位事实分开保存；
3. 自动从正式日终行情核验分笔成交额；
4. 接入申赎清单，将ETF份额变化投射到成分股理论需求；
5. 接入股指期货、期权和公司资本行为；
6. 完整 Level-2 可用后增加订单簿重建、真实OFI和撤单行为；
7. 对参与者假设进行样本外校准，记录命中率和失效状态。
