# 免费 T+1 分笔成交证据层

## 目标

本模块用免费的 AKShare/Tencent 最近交易日分笔成交数据，为重点股票建立可持续积累的 T+1 微观成交历史。

它只提供 **trade prints（分笔成交）** 能支持的证据，不把普通分笔成交包装为完整 Level-2。

## 能力分级

### trade_prints

需要时间、成交价格、成交量和成交额。可以计算：

- 供应方标记的买卖盘金额失衡；
- 可分类成交覆盖率；
- 大额成交集中度；
- 14:57 以后成交额占比；
- 分笔成交额与官方日终成交额的偏差。

不能计算：

- 真实订单流失衡 OFI；
- 撤单失衡；
- 订单存活时间；
- 隐藏大单拆分链路；
- 完整订单簿重建。

### full_l2

只有同时具备以下字段组时才允许标记为完整 L2：

- 连续消息序号；
- 委托或成交事件类型；
- 委托编号，或买卖双方订单编号；
- 价格；
- 数量。

缺少任一字段组时，`require_full_l2()` 会拒绝继续执行完整 L2 算法。

## 来源与权威等级

当前首个适配器：

```text
source_id: tick_akshare_tencent_tplus1
capability: trade_prints
authority_level: D
is_official: false
license_status: upstream_terms_unverified
```

供应方的“买盘/卖盘”属于分类结果，不等于交易所确认的交易者身份或主观意图。默认分类置信度为 0.55；中性盘和未知盘为 0。

## 命令行

```bash
a-stock-radar collect-ticks \
  --date 2026-07-31 \
  --symbols sz000001 sh600000
```

腾讯接口本身不返回交易日期，因此 `--date` 必须由操作方确认。清单中会记录：

```text
trade_date_is_operator_supplied: true
```

可以传入交易所或权威日终行情中的个股成交额进行核验：

```bash
a-stock-radar collect-ticks \
  --date 2026-07-31 \
  --symbols sz000001 sh600000 \
  --official-turnover sz000001=1234567890 \
  --official-turnover sh600000=987654321
```

默认允许分笔成交额与日终成交额存在 3% 偏差。未提供官方成交额时状态为 `provisional`；通过核验后为 `confirmed`；超过偏差或存在无效记录时为 `rejected`。

## 存储

```text
data/raw/tick_trade/
  date=20260731/
    code=000001.SZ/
      trade_prints.csv.gz
      manifest.json
```

`manifest.json` 包含：

- 来源能力与权威等级；
- 数据许可状态；
- 行数、重复数和无效行数；
- 第一笔和最后一笔时间；
- 分笔成交额；
- 官方成交额及偏差；
- 买卖盘分类覆盖率；
- 特征结果；
- 压缩数据文件 SHA-256；
- 固定限制说明。

## 规范化字段

```text
trade_date
 event_time
security_code
exchange
symbol
price
price_change
volume_lots
volume_shares
notional
vendor_side
side
trade_sign
classification_method
classification_confidence
source_id
capability
is_official
is_provisional
schema_version
```

其中腾讯成交量单位为“手”，规范化后同时保存 `volume_lots` 和乘以 100 后的 `volume_shares`；成交额统一为元。

## 指标解释

`signed_notional_imbalance` 定义为：

```text
(供应方标记买盘成交额 - 供应方标记卖盘成交额) / 全部分笔成交额
```

该值表示供应方分类下的成交主动性近似，不表示市场净流入，也不能识别机构、个人或最终受益人。

## 推荐运行范围

免费接口不适合每天无节制抓取全市场。首期建议每天保存 100 至 500 只：

- 重点 ETF 和成分股；
- 沪深 300 或自选核心池；
- 当日成交额前列股票；
- 涨停、跌停和异常波动股票；
- 项目重点跟踪行业。

证券之间默认等待 0.5 秒，并对单证券执行最多 3 次重试。

## 后续版本

1. 接入免费公开 L2 样本，开发沪深订单簿重建器；
2. 增加券商 QMT/ThinkTrader 录制适配器；
3. 接入正式日终个股成交额，自动完成 `confirmed` 核验；
4. 将分笔成交特征写入日报中的独立“微观成交证据”区域；
5. 完整 L2 可用后，再增加 OFI、撤单失衡、永久价格冲击和执行模式识别。
