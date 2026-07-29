# M1 Playwright + Mihomo 实现说明

## 数据路径

- Mihomo 从 `MIHOMO_PROVIDER_URL` 加载代理订阅；
- `RADAR-AUTO` 提供通用延迟排序；`RADAR-SELECT` 保存经目标 TLS/API 检测通过的固定节点；
- 本地监听 `socks5://127.0.0.1:7891`；
- Playwright 只连接本地 SOCKS5；
- AKShare 直连是第一顺位，Playwright 是东方财富市场行情和 ETF 行情的第二顺位；
- 交易所 ETF 份额、融资汇总和融资明细暂未实现浏览器专用适配，失败时继续按缺失处理。

## 故障隔离

- Mihomo 启动或订阅解析失败，不阻止日报降级生成；
- 浏览器每次数据源调用使用一个 Chromium 会话，并在会话内完成分页；
- HTTP 非 2xx、非 JSON、分页异常都会留下截图和 HTML；
- `diagnostics/mihomo.log`、`mihomo-proxies.json`、`proxy-smoke.json` 和浏览器诊断被上传为短期 Artifact；
- `runtime/` 与 `diagnostics/` 不进入 Git。

## 当前限制

- 订阅端点必须返回 Mihomo 可识别的订阅内容；
- 公共代理的可用性和访问地区不可保证；
- 浏览器回退只覆盖东方财富全市场行情与 ETF 行情；
- 不处理验证码、登录页或交互式验证；
- Python 只通过 Mihomo Controller 切换本地策略组，不读取或使用远端节点凭据。

## 2026-07 GitHub Actions 诊断修复

对运行 `30418545478` 的诊断包分析后，首要故障不是目标接口先拒绝浏览器，而是 Mihomo 的代理提供器发生自举循环：

```text
mergelist provider 下载请求
  → MATCH,RADAR-AUTO
  → RADAR-AUTO 尚无真实节点
  → 只剩 COMPATIBLE 占位项
  → provider 永远无法完成下载
```

本版修复包括：

- `proxy-provider.proxy` 固定为 `DIRECT`；
- 为 provider 域名增加显式 `DIRECT` 规则；
- 就绪检查必须确认 provider 和 `RADAR-AUTO` 中存在真实节点；
- 只有目标站点 SOCKS 冒烟测试成功才向抓取流程注入代理环境变量；
- 代理未就绪时恢复直连 HTTP 与直连 Playwright，避免坏掉的本地端口污染所有来源；
- 每次真实运行先清理 `data/raw/`、旧 provider 缓存和诊断目录，避免历史 mock 快照混入本次 Artifact。


## v0.2.4 目标 TLS 节点筛选

针对 `SSLEOFError` 和 Chromium `ERR_CONNECTION_CLOSED`，就绪流程不再只检查首页：

1. 从 provider 读取候选节点，优先选择 alive 且延迟较低的节点；
2. 通过 Controller 将节点写入 `RADAR-SELECT`；
3. 使用 `requests` 经 `socks5h://127.0.0.1:7891` 请求真实 `82.push2.eastmoney.com` 最小行情接口；
4. 校验 HTTP 状态、非 HTML、JSON/JSONP 格式及东方财富响应字段；
5. 再使用 Playwright Chromium 请求同一接口；
6. 两项通过后保留该节点，失败则继续下一个节点；
7. 所有结果写入 `diagnostics/proxy-node-validation.json`。

这项检测验证的是当前节点到目标域名的实际 TLS 和应用响应，不将“可访问其他 HTTPS 网站”误判为“可访问东方财富行情接口”。
