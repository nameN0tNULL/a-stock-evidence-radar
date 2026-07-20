# A股市场资金证据雷达 Agent

> 版本：V3.0  
> 文档类型：产品需求、数据设计、系统架构与开发实施规范  
> 目标读者：产品经理、数据工程师、后端工程师、量化研究人员、前端工程师、LLM 应用开发人员  
> 系统定位：面向金融初学者的 A 股市场状态观测、资金证据整理与复盘学习系统

---

## 1. 文档目的

本文件用于指导后续代码实现、数据接口建设、测试、回测和产品验收。

系统不尝试寻找一个能够代表全部市场资金的“主力净流入”，而是将资金活动拆分为多个可观测、可验证、可追溯的证据维度，回答以下问题：

1. 哪些可识别资金正在增加或减少风险敞口；
2. 资金变化发生在哪些市场、指数、行业或主题；
3. 资金变化是单日脉冲，还是具有连续性；
4. 资金变化是否得到价格、成交、市场宽度和相对强度确认；
5. 不同证据之间是互相印证，还是互相冲突；
6. 哪些判断来自官方事实，哪些来自模型估算，哪些目前无法确认；
7. 用户自选股处于怎样的市场与板块环境中；
8. 系统结论的置信度、反向证据和适用边界是什么。

最终产品输出为“每日市场资金证据与状态学习日报”，用于学习、观察和复盘，不构成投资建议。

---

## 2. 产品定位与非目标

### 2.1 产品定位

系统定位为：

```text
基于公开数据、强调证据分层和不确定性的 A 股市场状态观测 Agent。
```

系统核心价值：

```text
把交易所、基金管理人、上市公司、量化接口和财经门户中的分散数据，
整理成一份可读、可追溯、可比较、可复盘的市场证据报告。
```

### 2.2 系统能够回答的问题

- 市场整体参与度是增强、收缩还是分化；
- 上涨是否具有广度，还是集中在少数权重或龙头；
- ETF 工具型或配置型资金是否持续申购或赎回；
- 杠杆资金是否增加或降低风险敞口；
- 股指期货和期权是否显示风险敞口扩张、套保增强或波动预期变化；
- 北向通道参与活跃度是否提高，交易集中在哪些证券；
- 公司实际回购、增持、减持、解禁是否形成明确资本供需变化；
- 哪些行业或主题得到多个独立证据簇共同确认；
- 哪些板块只有成交情绪，没有真实持仓或份额变化支持；
- 哪些数据缺失、冲突或无法推断。

### 2.3 明确非目标

系统不承担以下功能：

- 不预测某只股票明日必涨或必跌；
- 不识别所谓“庄家”“主力真实意图”；
- 不把成交额错误解释为市场净流入；
- 不提供买入、卖出、仓位或止盈止损建议；
- 不自动交易；
- 不根据用户持仓生成个性化投资建议；
- 不将第三方资金流算法包装成官方事实；
- 不承诺消除用户情绪，只帮助用户降低单一叙事和短期波动的影响。

---

## 3. 核心认知原则

### 3.1 成交额不是净流入

二级市场每笔成交同时存在买方和卖方，因此：

```text
总成交额不能直接解释为市场净流入或净流出。
```

系统只讨论以下可观测对象：

- 持仓数量变化；
- 基金份额变化；
- 融资余额变化；
- 衍生品持仓和基差变化；
- 公司实际资本行为；
- 主动成交压力；
- 市场参与度和价格确认。

### 3.2 真实性不等于预测性

真实发生的 ETF 份额增加、融资余额增加或回购实施，能够说明某类资金敞口变化，但不能直接推出未来上涨。

报告必须区分：

```text
已经发生的事实
合理但有限的解释
尚未确认的推断
不能得出的结论
```

### 3.3 官方事实、模型估算和媒体叙事分层

所有字段必须携带证据级别，不允许混合展示。

| 级别 | 名称 | 典型数据 | 用途 |
|---|---|---|---|
| L1 | 硬持仓/硬份额证据 | ETF 总份额、融资余额、实际回购、季度持仓 | 判断已发生的敞口变化 |
| L2 | 官方活动/风险敞口证据 | 北向成交活跃度、期货持仓量、基差、期权持仓 | 判断参与和风险暴露 |
| L3 | 成交行为估算 | 主动买卖压力、订单失衡、门户资金流 | 描述交易压力，不识别身份 |
| L4 | 叙事与情绪辅助 | 新闻复盘、搜索热度、社区讨论 | 解释市场叙事，不进入核心事实层 |

### 3.4 不使用一个“真实资金总分”

系统输出多维资金状态，不把所有指标压缩成一个容易产生伪精确感的数字。

允许内部计算 0—100 的标准化强度和数据质量分，但前端默认展示：

- 历史百分位；
- 方向；
- 持续时间；
- 覆盖广度；
- 证据级别；
- 置信度等级；
- 支持证据；
- 反向证据。

---

## 4. 总体设计原则

### 4.1 自上而下

处理顺序固定为：

1. 交易日与数据源状态；
2. 市场宽度、成交和波动；
3. ETF 份额与资产类别资金；
4. 融资融券和杠杆敞口；
5. 股指期货、期权和风险对冲；
6. 北向参与活跃度与低频持仓锚点；
7. 公司资本行为；
8. 行业与主题证据聚合；
9. 媒体叙事和情绪；
10. 自选股作为板块结论验证。

### 4.2 风险和限制优先

每个报告必须首先展示：

- 数据是否齐全；
- 是否存在数据日期错位；
- 是否存在来源冲突；
- 哪些指标只能估算；
- 哪些结论无法从现有数据获得。

### 4.3 多时间尺度

每个核心指标至少计算：

- 1 日：当天变化；
- 5 日：短期持续性；
- 20 日：中期背景；
- 60 日或 250 日：历史百分位和异常程度。

### 4.4 反证机制

任何状态判断必须同时生成：

- 支持证据；
- 反向证据；
- 尚缺证据；
- 次日或后续确认条件。

### 4.5 证据簇去重

同一资金事件可能同时造成 ETF 份额变化、成分股成交放大和价格上涨。系统不得将这些结果重复计分。

先在证据簇内部合成，再在不同证据簇之间交叉验证。

---

## 5. 资金证据体系

## 5.1 ETF 份额与申购赎回证据簇

### 5.1.1 数据字段

- ETF 代码与名称；
- 跟踪指数或主题；
- 基金类型；
- 日终总份额；
- 基金份额净值；
- 收盘价；
- 成交额；
- 折溢价率；
- 最小申购赎回单位；
- 基金规模；
- 管理人；
- 数据日期与来源。

### 5.1.2 核心指标

```text
share_delta_t = total_shares_t - total_shares_t-1
estimated_creation_flow_t = share_delta_t × nav_t
```

若总资产和净值数据稳定，可使用：

```text
estimated_flow_t
= assets_t - assets_t-1 × (1 + nav_return_t)
```

### 5.1.3 聚合规则

- 同一指数或主题的多只 ETF 合并；
- 不仅观察单只规模最大的 ETF；
- 分开统计宽基、行业、主题、债券、商品、跨境 ETF；
- 计算资金方向覆盖率：份额增加 ETF 数量 / 有效 ETF 数量；
- 输出 1 日、5 日、20 日累计估算流量；
- 输出相对原有规模的流量比例；
- 标记新上市、清盘、份额合并拆分和异常事件。

### 5.1.4 解释边界

ETF 份额变化属于较硬证据，但可能包含套利、做市、跨市场对冲和申赎机制影响。

允许表达：

```text
相关 ETF 出现持续净申购估算，工具型或配置型资金参与增强。
```

禁止表达：

```text
机构确定看多该行业。
```

---

## 5.2 融资融券与杠杆资金证据簇

### 5.2.1 数据字段

- 融资余额；
- 融资买入额；
- 融资偿还额；
- 融券余量；
- 融券余额；
- 证券是否为当期融资融券标的；
- 自由流通市值；
- 成交额；
- 所属行业和主题。

### 5.2.2 核心指标

```text
margin_balance_delta_t
= margin_balance_t - margin_balance_t-1
```

```text
margin_balance_t
= margin_balance_t-1
+ margin_buy_t
- margin_repayment_t
```

```text
margin_intensity
= margin_balance_delta / free_float_market_cap
```

```text
margin_trade_ratio
= margin_buy_amount / turnover_amount
```

### 5.2.3 聚合规则

- 按行业、申万一级/二级行业和受控主题聚合；
- 使用余额变化，不单独以融资买入额代表净流入；
- 计算板块内融资余额增加股票占比；
- 对自由流通市值标准化；
- 剔除标的范围调整造成的结构断点；
- 标记融资余额异常但成交极低的证券。

### 5.2.4 状态解释

| 价格 | 融资余额 | 状态解释 |
|---|---|---|
| 上涨 | 增加 | 杠杆资金参与增强 |
| 上涨 | 减少 | 去杠杆上涨或空头回补等可能性，需要其他证据 |
| 下跌 | 增加 | 逆势加杠杆，可能承接，也可能形成套牢风险 |
| 下跌 | 减少 | 杠杆资金收缩或被动偿还 |

融资资金统一称为“杠杆交易资金”，不得称为聪明资金、机构资金或主力资金。

---

## 5.3 衍生品风险敞口证据簇

### 5.3.1 覆盖品种

- IF：沪深 300 股指期货；
- IH：上证 50 股指期货；
- IC：中证 500 股指期货；
- IM：中证 1000 股指期货；
- 沪深 300、中证 1000、上证 50 股指期权；
- 后续可扩展 ETF 期权。

### 5.3.2 数据字段

- 合约价格；
- 现货指数；
- 成交量；
- 持仓量；
- 合约到期日；
- 主力与次主力合约；
- 前 20 名会员成交和持仓排名；
- 认购/认沽成交与持仓；
- 隐含波动率；
- 期限结构；
- 数据日期。

### 5.3.3 核心指标

```text
basis = futures_price - spot_index
```

```text
annualized_basis
= basis / spot_index × 365 / days_to_expiry
```

```text
open_interest_delta
= open_interest_t - open_interest_t-1
```

```text
put_call_oi_ratio
= put_open_interest / call_open_interest
```

### 5.3.4 解释规则

| 价格 | 持仓量 | 解释 |
|---|---|---|
| 上涨 | 增加 | 新增风险敞口参与增强 |
| 上涨 | 减少 | 空头平仓或存量退出可能性上升 |
| 下跌 | 增加 | 新增空头或套保需求增强 |
| 下跌 | 减少 | 多头减仓或被动平仓可能性上升 |

期货多空头寸天然相等，系统不得将新增持仓称为净流入。

会员排名只代表经纪业务汇总，不得直接识别为机构或某类最终投资者。

---

## 5.4 北向参与度与持仓锚点证据簇

### 5.4.1 日频模块：北向参与活跃度

日频只使用当前官方可确认的数据：

- 沪股通、深股通成交总额；
- 成交笔数；
- ETF 成交总额；
- 前十大成交活跃证券；
- 活跃证券行业分布；
- 北向成交额占 A 股成交额比例；
- 月度和年度参与度比较。

日频输出：

```text
northbound_activity_level
northbound_activity_percentile
northbound_top10_concentration
northbound_active_sector_distribution
```

日频不得输出官方北向净流入、净买入行业或净增持个股。

### 5.4.2 低频模块：北向真实持仓变化

使用官方季度单只证券持有数量数据，计算：

- 持仓股数变化；
- 持仓市值变化；
- 剔除股价影响后的估算变化；
- 行业权重变化；
- 增持覆盖率；
- 新进入和退出名单。

### 5.4.3 第三方估算隔离

第三方日频北向方向估算必须单独存储：

```json
{
  "evidence_level": "L3_ESTIMATED",
  "official": false,
  "direction": "estimated_inflow",
  "confidence": "low",
  "allowed_for_core_label": false
}
```

不得与官方低频持仓数据混合计算。

---

## 5.5 公司资本行为证据簇

### 5.5.1 覆盖事件

- 回购计划；
- 实际回购进度；
- 重要股东增持；
- 重要股东减持；
- 解禁；
- 定增、配股；
- 可转债转股；
- 员工持股计划；
- 股权激励；
- 大宗交易辅助信息。

### 5.5.2 事件状态

必须区分：

```text
计划公告
开始实施
实施进展
实施完成
终止或变更
```

只有已实施金额进入实际资本行为指标。

```text
executed_buyback_amount
executed_increase_amount
executed_reduction_amount
unlock_market_value
```

### 5.5.3 标准化

```text
capital_action_intensity
= net_executed_amount / free_float_market_cap
```

公司行为只能说明资本供需变化，不能直接推断未来表现。

---

## 5.6 主动成交压力证据簇

### 5.6.1 免费 MVP

如缺少 Level-2，只保留门户估算作为低权重辅助，不进入硬资金结论。

### 5.6.2 Level-2 升级

接入后计算：

- 主动买入成交额；
- 主动卖出成交额；
- 主动成交失衡；
- 买卖盘订单失衡；
- 大额成交持续性；
- 撤单率；
- 成交价相对 VWAP；
- 尾盘 30 分钟成交占比；
- 收盘集合竞价成交占比。

```text
active_trade_imbalance
= (active_buy - active_sell) / total_turnover
```

该指标描述“哪一方更急于成交”，不识别交易者身份。

---

## 5.7 低频机构持仓锚点

覆盖：

- 公募基金季度持仓；
- 公募基金月度规模；
- 保险、社保、养老金、QFII 等公开持仓线索；
- 上市公司定期报告中的主要股东信息。

用途：

- 验证行业长期配置方向；
- 对日频信号进行背景校准；
- 不参与日频方向判断；
- 明确披露滞后。

---

## 5.8 跨资产风险偏好证据簇

覆盖：

- 宽基、行业、债券、黄金、跨境 ETF 份额；
- 可转债平均价格、溢价率和成交额；
- QDII、ETF、LOF 折溢价；
- 高股息指数和 REITs；
- 国债期货、债券 ETF；
- A/H 比价；
- 后续可扩展货币基金和公募基金规模。

输出不是“市场资金净流入”，而是：

- 风险资产参与度；
- 防守资产参与度；
- 跨境资产拥挤度；
- 杠杆和波动风险。

---

## 6. 市场与板块状态模型

## 6.1 市场基础状态

### 输入

- 主要指数收益；
- 全市场成交额及变化；
- 上涨、下跌、平盘家数；
- 涨停、跌停、炸板、连板；
- 新高、新低家数；
- 等权指数与市值加权指数差异；
- 波动率；
- 行业上涨覆盖率；
- 中位数股票收益。

### 输出

```json
{
  "market_state": "broad_strength | narrow_strength | divergence | contraction | panic | neutral",
  "breadth_percentile": 0,
  "turnover_percentile": 0,
  "volatility_percentile": 0,
  "concentration_percentile": 0,
  "confidence_level": "high | medium | low"
}
```

### 推荐中文标签

- 广泛改善；
- 权重主导；
- 局部活跃；
- 高度分化；
- 参与收缩；
- 恐慌释放；
- 中性整理。

不使用“牛市”“熊市”“主升浪”等强叙事标签作为日频输出。

---

## 6.2 板块资金状态向量

每个板块输出以下独立维度：

```json
{
  "sector_id": "sw1_801080",
  "trade_date": "YYYY-MM-DD",
  "flow_vector": {
    "etf_creation": {},
    "margin_exposure": {},
    "derivatives_exposure": {},
    "northbound_activity": {},
    "corporate_capital_action": {},
    "active_trade_pressure": {},
    "long_term_holding_anchor": {}
  },
  "market_confirmation": {
    "price_relative_strength": {},
    "breadth": {},
    "turnover": {},
    "persistence": {},
    "concentration": {}
  },
  "risk_vector": {
    "crowding": {},
    "reversal": {},
    "event_supply": {},
    "data_conflict": {}
  }
}
```

---

## 6.3 板块状态标签

不再使用“主线进攻”“强潜伏”“明显出货”等刺激性表达。

推荐状态：

1. **多证据参与增强**  
   至少两个独立硬证据簇增强，价格与广度确认，持续性达到要求。

2. **配置型资金改善**  
   ETF 份额或低频持仓改善，但杠杆资金不强。

3. **杠杆主导活跃**  
   融资余额明显增加，但 ETF 和长期持仓证据不足。

4. **成交情绪脉冲**  
   主动成交和换手强，但硬持仓、份额证据不足。

5. **局部集中上涨**  
   龙头或少数权重贡献较大，板块广度不足。

6. **多证据分歧**  
   不同资金簇方向冲突，或价格与资金证据背离。

7. **参与度收缩**  
   ETF、融资或成交广度等多个维度转弱。

8. **高拥挤与反转风险**  
   历史涨幅、估值、换手、集中度和价格反转证据共同偏高。

9. **数据不足**  
   数据完整性或样本不足，不输出方向判断。

---

## 7. 状态判定规则

## 7.1 判定维度

每个证据必须评估：

- 方向：增加、减少、中性、未知；
- 强度：历史百分位；
- 持续性：连续有效天数；
- 广度：板块内证券覆盖比例；
- 独立性：是否属于独立证据簇；
- 数据质量：权威性、完整性、新鲜度；
- 价格确认：相对强度、宽度和成交是否确认；
- 反向证据：是否存在显著冲突。

## 7.2 初始规则示例

```python
def classify_sector_state(evidence, confirmation, risk, quality):
    if quality.level == "low":
        return "数据不足"

    hard_positive = evidence.count_positive(levels={"L1", "L2"}, independent=True)
    hard_negative = evidence.count_negative(levels={"L1", "L2"}, independent=True)

    if risk.crowding_percentile >= 90 and risk.reversal_confirmed:
        return "高拥挤与反转风险"

    if hard_positive >= 2 and confirmation.breadth_percentile >= 60 \
       and confirmation.persistence_days >= 3 \
       and confirmation.relative_strength_positive:
        return "多证据参与增强"

    if evidence.etf_creation.positive and not evidence.margin_exposure.positive:
        return "配置型资金改善"

    if evidence.margin_exposure.positive and not evidence.etf_creation.positive:
        return "杠杆主导活跃"

    if evidence.active_trade_pressure.strong \
       and hard_positive == 0:
        return "成交情绪脉冲"

    if confirmation.concentration_percentile >= 85 \
       and confirmation.breadth_percentile < 50:
        return "局部集中上涨"

    if hard_positive > 0 and hard_negative > 0:
        return "多证据分歧"

    if hard_negative >= 2 and confirmation.breadth_percentile < 40:
        return "参与度收缩"

    return "中性观察"
```

阈值均为 MVP 初始参数，不代表概率，必须通过历史样本校准。

---

## 8. 标准化、百分位和缺失值

## 8.1 标准化

- 优先使用滚动 250 交易日历史百分位；
- 样本不足 250 日时最低要求 60 日；
- 对极端值进行 1%—99% Winsorize；
- 对规模型指标使用自由流通市值、基金规模或成交额归一化；
- 行业间比较使用行业内历史标准化，不直接比较绝对金额；
- 新上市 ETF、指数和证券单独标记，不强行参与长期百分位。

## 8.2 缺失值

- 缺失值不得填充为 0；
- 保存 `is_missing`、`missing_reason` 和 `last_available_date`；
- 数据源失败时降低置信度，不使用陈旧值冒充当天值；
- 允许输出方向 `unknown`；
- 当关键 L1 数据缺失时，不得输出高置信度资金方向。

## 8.3 数据修订

- 保存首次抓取值和最终确认值；
- 使用 `data_version` 和 `retrieved_at`；
- 允许盘后初版和次日确认版并存；
- 回测只能使用当时可获得的 point-in-time 数据，防止未来数据泄漏。

---

## 9. 数据置信度体系

## 9.1 内部评分

```text
confidence_score
= 30% × source_authority
+ 25% × completeness
+ 20% × cross_source_consistency
+ 15% × freshness
+ 10% × sample_sufficiency
```

该分数仅用于内部排序和规则控制，前端默认显示等级及原因。

## 9.2 前端等级

- 高：关键硬证据齐全、日期一致、多个独立证据簇确认；
- 中：核心数据可用，但存在一个重要缺口或部分冲突；
- 低：缺少关键硬证据、数据过期、样本不足或主要来源冲突。

## 9.3 必须输出的原因字段

```json
{
  "confidence_level": "medium",
  "positive_reasons": [
    "ETF总份额和融资余额数据完整",
    "价格与板块广度方向一致"
  ],
  "negative_reasons": [
    "衍生品数据缺失",
    "北向仅能确认参与活跃度，无法确认日净方向"
  ]
}
```

---

## 10. 证据去重设计

## 10.1 证据簇

| 证据簇 | 主证据 | 辅助证据 |
|---|---|---|
| 配置工具资金 | ETF 份额变化 | ETF 规模、折溢价、成交额 |
| 杠杆资金 | 融资余额变化 | 融资买入比例、融券数据 |
| 衍生品敞口 | 持仓量、基差 | 会员排名、期权指标 |
| 北向参与 | 官方成交活跃度 | 活跃证券集中度 |
| 公司资本行为 | 已实施回购/增减持 | 计划金额、大宗交易 |
| 成交压力 | 主动成交失衡 | 换手、尾盘成交、门户估算 |
| 长期持仓锚点 | 季度持仓变化 | 基金规模、股东结构 |
| 市场确认 | 价格、宽度、持续性 | 成交额、波动、集中度 |

## 10.2 去重规则

- 每个证据簇最多贡献一次方向确认；
- 辅助指标只增强簇内置信度，不增加独立证据数量；
- 价格、成交和涨停属于市场确认，不作为新增资金证据；
- ETF 申购引发的成分股成交放大不得重复计为两类硬资金；
- 主题板块高度重叠时按成分股权重去重；
- 同一只股票同时属于多个概念时，使用受控标签和归因权重。

---

## 11. 数据源分层与接入规范

## 11.1 S 层：官方权威源

- 上交所：行情、ETF 总份额和 PCF、融资融券、沪股通成交活跃度、交易公开信息；
- 深交所：ETF、融资融券、深股通成交活跃度、交易公开信息；
- 中金所：股指期货、股指期权、成交持仓排名；
- 港交所：互联互通规则及相关统计；
- 巨潮资讯：上市公司公告；
- 基金管理人官网：ETF 公告、基金净值和定期报告；
- 证监会、基金业协会：规则和行业低频统计。

## 11.2 A 层：结构化接口

- AKShare；
- Tushare；
- BaoStock；
- 经许可的数据供应商。

结构化接口用于自动化，不自动获得高于原始来源的权威等级。

## 11.3 B 层：财经门户

- 东方财富；
- 同花顺；
- 新浪财经；
- 腾讯财经。

用途：

- 发现数据入口；
- 备用行情；
- 板块映射参考；
- 第三方成交行为估算。

门户“资金流”默认属于 L3，不进入硬资金方向结论。

## 11.4 C 层：特色指标和媒体

- 集思录；
- 乐咕乐股；
- 理杏仁；
- 财经媒体；
- 手动复盘摘要。

仅用于跨资产辅助、估值背景和叙事解释。

## 11.5 数据源契约

每个 source adapter 必须配置：

```yaml
source_id: sse_etf_shares
display_name: 上交所ETF总份额
authority_level: S
evidence_level: L1
official: true
frequency: daily
expected_delay: T_end_of_day
license_note: public_page
parser_version: 1.0.0
critical_fields:
  - trade_date
  - fund_code
  - total_shares
fallback_sources: []
```

---

## 12. 核心数据模型

## 12.1 通用证据模型

```python
class EvidenceRecord(BaseModel):
    evidence_id: str
    trade_date: date
    entity_type: Literal["market", "sector", "security", "fund", "index"]
    entity_id: str
    cluster: str
    metric: str
    value: float | None
    unit: str | None
    direction: Literal["positive", "negative", "neutral", "unknown"]
    horizon: Literal["1d", "5d", "20d", "60d", "quarterly"]
    percentile: float | None
    evidence_level: Literal["L1", "L2", "L3", "L4"]
    official: bool
    source_id: str
    source_date: date
    retrieved_at: datetime
    parser_version: str
    is_estimated: bool
    is_missing: bool
    missing_reason: str | None
    quality_score: float
    explanation_key: str
```

## 12.2 板块状态模型

```python
class SectorState(BaseModel):
    trade_date: date
    sector_id: str
    sector_name: str
    taxonomy: str
    state_label: str
    evidence_summary: list[EvidenceRecord]
    supporting_evidence: list[str]
    counter_evidence: list[str]
    unknowns: list[str]
    next_confirmation_conditions: list[str]
    confidence_level: Literal["high", "medium", "low"]
    internal_confidence_score: float
```

## 12.3 来源质量模型

```python
class SourceQuality(BaseModel):
    source_id: str
    trade_date: date
    available: bool
    expected_date: date
    actual_date: date | None
    freshness_ok: bool
    schema_ok: bool
    row_count: int
    anomaly_count: int
    checksum: str | None
    error_message: str | None
```

---

## 13. 系统架构

## 13.1 MVP 架构

```text
GitHub Actions / 手动任务
  ↓
官方与结构化数据抓取
  ↓
原始快照不可变存储
  ↓
标准化与实体映射
  ↓
数据质量与日期检查
  ↓
证据指标计算
  ↓
证据簇合成与去重
  ↓
市场/板块状态规则引擎
  ↓
LLM 仅做解释和日报生成
  ↓
JSON + Markdown + 静态 HTML
  ↓
GitHub Pages 或 Render Static Site
```

## 13.2 运行时机

建议采用两阶段任务：

1. **盘后初版**：北京时间 20:30，生成行情、ETF、互联互通活跃度和公告初版；
2. **最终确认版**：北京时间 23:15，补充融资融券等晚间数据；
3. **失败补跑**：次日 06:30，仅在关键数据缺失时运行。

初版必须显示 `preliminary`，最终版显示 `confirmed`。

## 13.3 存储策略

第一阶段使用 Git 仓库文件存储：

```text
data/
  raw/
    YYYY-MM-DD/
      sse/
      szse/
      cffex/
      hkex/
      cninfo/
      fund_managers/
      portals/
  normalized/
    YYYY-MM-DD/
  evidence/
    YYYY-MM-DD/
  states/
    YYYY-MM-DD/
reports/
  daily/
  latest/
metadata/
  source_registry.yaml
  sector_taxonomy.yaml
  instrument_mapping.parquet
```

长期历史或数据量扩大后迁移到 PostgreSQL、ClickHouse 或对象存储。

---

## 14. 项目目录结构

```text
a_stock_evidence_radar/
├── app/
│   ├── main.py
│   ├── api/
│   ├── pages/
│   └── static/
├── config/
│   ├── app.yaml
│   ├── sources.yaml
│   ├── thresholds.yaml
│   ├── sector_taxonomy.yaml
│   └── watchlist.yaml
├── domain/
│   ├── models.py
│   ├── enums.py
│   └── contracts.py
├── data_sources/
│   ├── official/
│   │   ├── sse/
│   │   ├── szse/
│   │   ├── cffex/
│   │   ├── hkex/
│   │   └── cninfo/
│   ├── fund_managers/
│   ├── structured/
│   │   ├── akshare_client.py
│   │   └── tushare_client.py
│   ├── portals/
│   └── media/
├── normalizers/
│   ├── market.py
│   ├── etf.py
│   ├── margin.py
│   ├── derivatives.py
│   ├── northbound.py
│   ├── corporate_actions.py
│   └── holdings.py
├── mappings/
│   ├── instrument_master.py
│   ├── sector_mapper.py
│   ├── etf_theme_mapper.py
│   └── taxonomy_version.py
├── quality/
│   ├── schema_check.py
│   ├── freshness_check.py
│   ├── date_consistency.py
│   ├── anomaly_detection.py
│   └── cross_source_check.py
├── features/
│   ├── market_breadth.py
│   ├── etf_creation_flow.py
│   ├── margin_exposure.py
│   ├── derivatives_exposure.py
│   ├── northbound_activity.py
│   ├── corporate_capital_action.py
│   ├── active_trade_pressure.py
│   ├── cross_asset.py
│   └── rolling_percentiles.py
├── evidence/
│   ├── builder.py
│   ├── cluster.py
│   ├── deduplicator.py
│   └── confidence.py
├── states/
│   ├── market_state.py
│   ├── sector_state.py
│   ├── risk_state.py
│   └── rules.py
├── llm/
│   ├── client.py
│   ├── prompts.py
│   ├── serializers.py
│   └── guardrails.py
├── reports/
│   ├── renderer.py
│   ├── templates/
│   └── glossary.py
├── jobs/
│   ├── run_preliminary.py
│   ├── run_confirmed.py
│   ├── retry_missing_sources.py
│   └── backfill.py
├── storage/
│   ├── raw_store.py
│   ├── processed_store.py
│   └── paths.py
├── backtest/
│   ├── point_in_time_loader.py
│   ├── calibration.py
│   ├── stability.py
│   └── evaluation.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── data_quality/
│   ├── regression/
│   └── prompt_guardrails/
├── data/
├── metadata/
├── .github/workflows/
├── pyproject.toml
├── render.yaml
└── README.md
```

---

## 15. 主流程

```python
def run_daily_radar(trade_date: date, report_stage: str):
    calendar = resolve_trade_calendar(trade_date)

    raw = fetch_all_sources(
        trade_date=trade_date,
        stage=report_stage,
    )

    normalized = normalize_all(raw)

    source_quality = validate_sources(
        normalized=normalized,
        trade_date=trade_date,
    )

    instrument_master = load_instrument_master(trade_date)
    taxonomy = load_sector_taxonomy(trade_date)

    features = build_features(
        normalized=normalized,
        instrument_master=instrument_master,
        taxonomy=taxonomy,
    )

    evidence_records = build_evidence_records(
        features=features,
        source_quality=source_quality,
    )

    evidence_clusters = cluster_and_deduplicate(evidence_records)

    market_state = classify_market_state(
        evidence_clusters=evidence_clusters,
        features=features,
    )

    sector_states = classify_sector_states(
        evidence_clusters=evidence_clusters,
        market_state=market_state,
        features=features,
    )

    report_payload = build_report_payload(
        market_state=market_state,
        sector_states=sector_states,
        source_quality=source_quality,
        stage=report_stage,
    )

    report_md = generate_explanation_with_llm(report_payload)
    validate_report_guardrails(report_md, report_payload)

    save_all_outputs(...)
```

---

## 16. LLM 职责与约束

## 16.1 LLM 只负责

- 把结构化结论解释成小白能懂的话；
- 解释专业术语；
- 整理支持证据、反向证据和未知项；
- 生成每日学习日报；
- 生成后续观察条件；
- 在数据冲突或缺失时明确说明限制。

## 16.2 LLM 不负责

- 计算原始指标；
- 决定状态标签；
- 修改置信度；
- 补充输入中不存在的新闻或事实；
- 推断交易者身份；
- 给出交易建议。

## 16.3 系统 Prompt 核心约束

```text
你是面向金融初学者的 A 股市场证据解释助手。

你只能解释输入 JSON 中已经给出的事实、规则结论和限制。
不得补充输入以外的市场信息。
不得将成交额称为净流入。
不得将主动成交压力称为机构资金或主力资金。
不得将北向成交活跃度解释为北向净买入。
不得将评分解释为上涨概率。

每个结论必须按以下结构输出：
1. 已确认事实；
2. 合理解释；
3. 反向证据；
4. 无法确认；
5. 后续确认条件。

禁止输出：
买入、卖出、满仓、梭哈、必涨、稳赚、抄底、逃顶、内幕、
庄家、主力吸筹、主力出货、明天一定上涨。

报告仅用于学习、观察和复盘，不构成投资建议。
```

## 16.4 输出校验

LLM 生成后必须运行：

- 禁词检测；
- 数值与 JSON 一致性检测；
- 未知事实检测；
- 官方/估算标签一致性检测；
- 必备章节检测；
- 风险声明检测。

失败时使用规则模板降级生成报告，不直接发布异常文本。

---

## 17. 日报设计

```text
# A股市场资金证据雷达日报：YYYY-MM-DD

## 0. 报告状态与数据源
- 初版/确认版
- 缺失来源
- 日期一致性
- 本日报不能确认的事项

## 1. 今日市场基础状态
- 市场宽度
- 成交与波动
- 等权/权重差异
- 1日、5日、20日背景

## 2. 可识别资金证据总览
- ETF份额
- 融资杠杆
- 衍生品敞口
- 北向参与度
- 公司资本行为
- 低频持仓锚点

## 3. 多证据参与增强板块

## 4. 配置型资金改善板块

## 5. 杠杆主导活跃板块

## 6. 成交情绪脉冲板块

## 7. 多证据分歧板块

## 8. 参与度收缩与高拥挤风险

## 9. 自选股与市场/板块关系

## 10. 后续确认条件

## 11. 小白学习笔记

## 12. 风险与限制声明
```

每个板块固定显示：

```text
【已确认事实】
【合理解释】
【反向证据】
【无法确认】
【后续确认条件】
【数据置信度】
```

---

## 18. 页面与 API 设计

## 18.1 页面

```text
/dashboard/market
/dashboard/sectors
/dashboard/sector/{sector_id}
/dashboard/sources
/dashboard/watchlist
/reports/latest
```

首页不显示刺激性的 Top 1、Top 2 排名，而按状态分组。

默认先展示市场事实和数据状态，再展示板块结论。

### 主要卡片

- 报告阶段与数据完整度；
- 市场宽度与成交；
- ETF 份额变化；
- 融资余额变化；
- 衍生品风险敞口；
- 北向参与活跃度；
- 公司资本行为；
- 多证据分歧；
- 高拥挤风险；
- 术语解释。

## 18.2 API

```text
GET /api/v3/latest
GET /api/v3/market-state
GET /api/v3/sector-states
GET /api/v3/sectors/{sector_id}
GET /api/v3/evidence/{entity_type}/{entity_id}
GET /api/v3/source-quality
GET /api/v3/reports/latest
GET /api/v3/glossary
```

API 返回必须包含：

- `trade_date`；
- `report_stage`；
- `generated_at`；
- `data_version`；
- `source_dates`；
- `confidence_level`；
- `unknowns`。

---

## 19. 行为降噪设计

为了减少系统本身成为新的情绪源，产品必须执行：

1. 只在盘后固定更新，不提供盘中滚动“资金榜”；
2. 默认展示 1 日、5 日和 20 日，而不是只显示当天；
3. 不使用红色“机会榜”和绿色“风险榜”式刺激设计；
4. 不显示“买点”“卖点”“潜伏成功率”；
5. 所有高强度状态同时显示反向证据；
6. 不将单日强度自动推送为机会提醒；
7. 状态变化必须满足最短持续条件，减少标签来回跳变；
8. 明确显示“本系统不能告诉你什么”；
9. 自选股只解释其与市场环境的关系，不输出动作建议；
10. 用户可查看原始来源、计算过程和历史状态变化。

---

## 20. 测试策略

## 20.1 单元测试

- ETF 份额差和估算流量；
- 融资余额恒等式；
- 期货基差和年化；
- 滚动百分位；
- 缺失值；
- 证据簇去重；
- 状态规则；
- 置信度计算。

## 20.2 数据质量测试

- 日期一致性；
- 交易日校验；
- 字段类型；
- 单位变更；
- 行数异常；
- 极端值；
- 份额拆分、合并和新上市；
- 行业分类版本变化；
- 来源页面结构变化；
- 重复记录与主键冲突。

## 20.3 集成测试

- 完整盘后流程；
- 单一来源失败；
- 多来源冲突；
- LLM 超时或失败时规则模板降级；
- 静态页面生成；
- Git 提交和部署；
- 补跑与幂等性。

## 20.4 Point-in-time 测试

- 回测只能读取当时已经披露的数据；
- 季报、公告按真实披露时间生效；
- 不使用事后修订值覆盖历史初始值；
- 行业成分和 ETF 映射按当时版本；
- 避免幸存者偏差和未来函数。

## 20.5 Prompt Guardrail 测试

必须测试以下违规输出：

- 把成交额称为净流入；
- 把北向活跃度称为净买入；
- 把融资资金称为机构资金；
- 把评分称为上涨概率；
- 输出买卖建议；
- 编造输入中不存在的事件。

---

## 21. 回测与校准

回测目的不是证明系统能够赚钱，而是验证状态标签是否稳定、是否具有解释力。

### 21.1 评估指标

- 标签次日反转率；
- 标签 5 日持续率；
- 资金证据与价格确认的一致性；
- 多证据状态与单一成交指标的差异；
- 假阳性率；
- 数据缺失情况下的错误输出率；
- 高拥挤风险后续最大回撤分布；
- 参与度收缩后市场宽度变化；
- 标签日均切换次数；
- 置信度与实际稳定性的校准关系。

### 21.2 对照组

至少与以下基线比较：

- 仅使用板块涨跌幅；
- 仅使用门户资金流；
- 仅使用成交额变化；
- ETF 份额单指标；
- 融资余额单指标；
- 多证据模型。

### 21.3 阈值管理

- 初始阈值存储在配置文件中；
- 不把阈值硬编码在业务代码；
- 保存阈值版本；
- 每次调整必须生成回测报告；
- 样本外验证后才允许进入生产；
- 前端不把阈值解释为概率。

---

## 22. 监控、审计与异常处理

### 22.1 运行监控

- 任务成功率；
- 各来源抓取时长；
- 数据新鲜度；
- 空值率；
- 行数变化；
- 页面结构变更；
- LLM 调用失败率；
- 报告校验失败率。

### 22.2 审计字段

每个最终结论必须可追溯到：

```text
状态标签
→ 证据簇
→ 指标
→ 标准化结果
→ 原始数据
→ 来源与抓取时间
→ 解析器版本
```

### 22.3 降级策略

- 关键 L1 数据缺失：输出“数据不足”，不猜测；
- 门户数据缺失：不影响硬证据主流程；
- LLM 失败：使用规则模板生成；
- 页面部署失败：保留仓库中的 JSON 和 Markdown；
- 数据日期错误：停止发布确认版；
- 单一板块映射异常：隔离该板块，不影响全市场报告。

---

## 23. 隐私与安全

- 不采集用户账户、资金余额、成本价和交易记录；
- 自选股仅保存证券代码和可选备注；
- 不把用户真实持仓发送给第三方 LLM；
- LLM 输入仅包含公开市场数据和规则结果；
- API Key 通过 GitHub Secrets 或部署平台密钥管理；
- 日志不得输出密钥和完整请求头；
- 所有外部数据均保存来源和使用说明；
- 商业化前检查数据授权、抓取频率和再分发限制。

---

## 24. MVP 实施路线

## M0：工程骨架与数据契约

交付：

- 项目目录；
- Pydantic 模型；
- source registry；
- 交易日历；
- mock 数据；
- 原始、标准化、证据、状态四层存储；
- 基础 CI 和测试。

## M1：市场、ETF 和融资核心闭环

接入：

- 市场行情和宽度；
- ETF 总份额、净值、分类；
- 融资余额和融资买入；
- 板块映射；
- 1/5/20/250 日指标；
- 配置型资金改善、杠杆主导活跃和多证据分歧状态；
- 静态日报。

这是首个可对外展示的 MVP。

## M2：衍生品、北向参与度和公司资本行为

接入：

- IF/IH/IC/IM；
- 股指期权；
- 北向成交活跃度；
- 北向季度持仓；
- 回购、增持、减持、解禁；
- 跨资产风险偏好。

## M3：回测和阈值校准

交付：

- point-in-time 数据加载；
- 阈值版本化；
- 稳定性、假阳性和状态持续性报告；
- 生产阈值更新流程。

## M4：Level-2 和微观结构增强

接入：

- 逐笔成交；
- 主动买卖压力；
- 订单簿失衡；
- 收盘集合竞价；
- 尾盘执行行为。

L3 证据仍不得覆盖 L1、L2 的硬证据结论。

---

## 25. MVP 验收标准

M1 完成后至少满足：

1. 交易日任务可手动和定时运行；
2. 原始数据按来源和日期保存；
3. 数据日期、字段和异常值可校验；
4. ETF 总份额变化可计算；
5. 同类 ETF 可聚合并去重；
6. 融资余额变化可计算；
7. 指标具有 1、5、20 日和历史百分位；
8. 缺失值不会被填为 0；
9. 每个证据带来源、时间、级别和是否估算；
10. 每个板块能够生成支持证据和反向证据；
11. 系统能够区分配置型改善、杠杆主导、成交脉冲和数据分歧；
12. 不输出“主力净流入”；
13. 不输出北向日净买入；
14. 不把成交额称为资金净流入；
15. 不把融资资金称为机构资金；
16. LLM 不负责评分和标签；
17. LLM 失败时可以降级生成模板报告；
18. 报告包含“无法确认”和“后续确认条件”；
19. 静态页面可展示最新确认版；
20. 所有结论可追溯到原始数据；
21. 至少有一套历史回放集成测试；
22. Prompt guardrail 测试全部通过；
23. 自选股不产生买卖建议；
24. 数据源冲突时降低置信度；
25. 关键数据缺失时输出“数据不足”。

---

## 26. 最终产品输出示例

```text
板块：半导体
状态：多证据参与增强
置信度：中

【已确认事实】
近5个交易日，相关ETF总份额持续增加；
板块融资余额增加，且增加覆盖率高于自身历史中位数；
板块内多数成分股相对全市场表现改善。

【合理解释】
配置工具资金与杠杆交易资金的参与度同时增强，
且不是仅由单一龙头贡献。

【反向证据】
板块换手和短期涨幅已处于较高历史百分位；
部分衍生品指标显示波动预期上升。

【无法确认】
无法确认具体买方身份；
无法根据北向日频数据确认外资净买入方向；
不能据此判断板块未来一定上涨。

【后续确认条件】
观察ETF份额是否继续增加；
观察融资余额是否在价格回落时快速下降；
观察板块上涨覆盖率是否维持，而非重新集中到少数龙头。
```

---

## 27. 最终系统原则

```text
先看事实，再看解释；
先分资金类型，再谈方向；
先看持仓和份额，再看成交压力；
先看持续性和广度，再看单日强弱；
先找反向证据，再下状态结论；
可以明确不知道，不用假装精确；
描述已经发生的市场，不预测尚未发生的结果。
```

