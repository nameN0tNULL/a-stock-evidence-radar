# A股市场资金证据雷达日报：2026-07-29

> 报告阶段：confirmed  
> 数据模式：live  
> 生成时间：2026-07-29 06:16:11.382214+00:00  
> 本报告用于学习、观察和复盘，不构成投资建议。

## 0. 报告状态与数据源


| 数据源 | 证据级别 | 状态 | 日期一致 | 行数 | 说明 |
|---|---:|---|---|---:|---|
| A股实时行情聚合 | L2 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='82.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3A1+t%3A23%2Cm%3A0+t%3A81+s%3A2048&fields=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf12%2Cf13%2Cf14%2Cf15%2Cf16%2Cf17%2Cf18%2Cf20%2Cf21%2Cf23%2Cf24%2Cf25%2Cf22%2Cf11%2Cf62%2Cf128%2Cf136%2Cf115%2Cf152 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))); Playwright fallback: Error: Page.goto: net::ERR_CONNECTION_CLOSED at https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=2&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3A1+t%3A23%2Cm%3A0+t%3A81+s%3A2048&fields=f2%2Cf3%2Cf6%2Cf8%2Cf12%2Cf14%2Cf20%2Cf21
Call log:
  - navigating to "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=2&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3A1+t%3A23%2Cm%3A0+t%3A81+s%3A2048&fields=f2%2Cf3%2Cf6%2Cf8%2Cf12%2Cf14%2Cf20%2Cf21", waiting until "domcontentloaded"
 |
| ETF行情与IOPV聚合 | L2 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='push2delay.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&wbp2u=%7C0%7C0%7C0%7Cweb&fid=f12&fs=b%3AMK0021%2Cb%3AMK0022%2Cb%3AMK0023%2Cb%3AMK0024%2Cb%3AMK0827&fields=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf12%2Cf13%2Cf14%2Cf15%2Cf16%2Cf17%2Cf18%2Cf20%2Cf21%2Cf23%2Cf24%2Cf25%2Cf22%2Cf11%2Cf30%2Cf31%2Cf32%2Cf33%2Cf34%2Cf35%2Cf38%2Cf62%2Cf63%2Cf64%2Cf65%2Cf66%2Cf69%2Cf72%2Cf75%2Cf78%2Cf81%2Cf84%2Cf87%2Cf115%2Cf124%2Cf128%2Cf136%2Cf152%2Cf184%2Cf297%2Cf402%2Cf441 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))); Playwright fallback: Error: Page.goto: net::ERR_CONNECTION_CLOSED at https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&wbp2u=%7C0%7C0%7C0%7Cweb&fid=f12&fs=b%3AMK0021%2Cb%3AMK0022%2Cb%3AMK0023%2Cb%3AMK0024%2Cb%3AMK0827&fields=f2%2Cf3%2Cf6%2Cf12%2Cf14%2Cf38%2Cf402%2Cf441
Call log:
  - navigating to "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&wbp2u=%7C0%7C0%7C0%7Cweb&fid=f12&fs=b%3AMK0021%2Cb%3AMK0022%2Cb%3AMK0023%2Cb%3AMK0024%2Cb%3AMK0827&fields=f2%2Cf3%2Cf6%2Cf12%2Cf14%2Cf38%2Cf402%2Cf441", waiting until "domcontentloaded"
 |
| 上交所ETF基金份额 | L1 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='query.sse.com.cn', port=443): Max retries exceeded with url: /commonQuery.do?isPagination=true&pageHelp.pageSize=10000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=2026-07-29 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))) |
| 深交所ETF基金份额 | L1 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='www.szse.cn', port=443): Max retries exceeded with url: /api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=scsj_fund_jjgm&TABKEY=tab1&txtStart=2026-07-29&txtEnd=2026-07-29&jjlb=ETF&random=0.05352524025369987 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))) |
| 上交所融资融券汇总 | L1 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='query.sse.com.cn', port=443): Max retries exceeded with url: /marketdata/tradedata/queryMargin.do?isPagination=true&beginDate=20260729&endDate=20260729&tabType=&stockCode=&pageHelp.pageSize=5000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=5 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))) |
| 深交所融资融券汇总 | L1 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='www.szse.cn', port=443): Max retries exceeded with url: /api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=1837_xxpl&txtDate=2026-07-29&tab1PAGENO=1&random=0.7425245522795993 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))) |
| 沪深融资融券明细 | L1 | 缺失 | 否 | 0 | SSLError: HTTPSConnectionPool(host='query.sse.com.cn', port=443): Max retries exceeded with url: /marketdata/tradedata/queryMargin.do?isPagination=true&tabType=mxtype&detailsDate=20260729&stockCode=&beginDate=&endDate=&pageHelp.pageSize=5000&pageHelp.pageCount=50&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=21 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))); SSLError: HTTPSConnectionPool(host='www.szse.cn', port=443): Max retries exceeded with url: /api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1837_xxpl&txtDate=2026-07-29&tab2PAGENO=1&random=0.24279342734085696&TABKEY=tab2 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)'))) |

**本日报不能确认的事项：**
- 无法确认具体交易者身份，也无法识别所谓真实意图。
- 成交额只表示成交活跃程度，不能解释为市场净流入或净流出。
- ETF份额变化和融资余额变化描述已经发生的敞口变化，不代表未来价格结果。
- M1不使用北向日净额，也不包含衍生品和公司资本行为证据。
- 以下来源缺失或异常：A股实时行情聚合、ETF行情与IOPV聚合、上交所ETF基金份额、深交所ETF基金份额、上交所融资融券汇总、深交所融资融券汇总、沪深融资融券明细。
- 行情聚合数据属于结构化接口结果，应以交易所正式披露为最终依据。

## 1. 今日市场基础状态

**状态：数据不足；数据置信度：low。**

- 无法确认：市场宽度数据缺失，无法确认市场参与状态。

## 2. 可识别资金证据总览

- 市场上涨覆盖率：数据不足
- 市场成交额：数据不足
- 全市场融资余额：数据不足
- 融资余额近5日变化：数据不足
- ETF证据采用份额变化乘以净值代理进行估算；它描述工具型或配置型资金敞口，不识别具体交易者身份。


## 10. 后续确认条件

- 优先观察ETF份额变化能否持续3至5个交易日，而不是只看单日成交放大。
- 观察融资余额变化是否与ETF份额证据同方向；方向冲突时保持“多证据分歧”。
- 观察价格改善是否具有覆盖广度，避免把单只ETF或少数权重的表现解释为整个主题改善。
- 当关键L1数据缺失时，继续输出“数据不足”，不使用陈旧值替代当日事实。

## 11. 小白学习笔记

- **ETF份额变化**：份额增加通常意味着发生了净申购，但也可能包含套利、做市和对冲。
- **融资余额变化**：描述杠杆交易资金敞口变化，不等同于机构资金。
- **市场宽度**：上涨证券占有效证券的比例，用来判断改善是否普遍。
- **历史百分位**：只表示当前指标在自身历史中的相对位置，不代表未来上涨概率。

## 12. 风险与限制声明

本系统只整理公开市场数据和规则结果。它不能确认具体交易者身份，不能确认所谓真实意图，也不能根据当前证据推断未来价格必然方向。数据接口可能延迟、修订或中断；第三方聚合数据应以交易所和基金管理人的正式披露为最终依据。本报告仅用于学习、观察和复盘，不构成投资建议。