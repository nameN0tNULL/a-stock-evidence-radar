# A股市场资金证据雷达 M1

这是 V3 设计的首个可部署版本，使用 GitHub Actions 盘后批处理并通过 GitHub Pages 发布静态日报。

## M1 已实现

- A股市场宽度、成交额、等权与市值加权表现；
- 上交所、深交所 ETF 日终份额适配；
- ETF 份额变化、1/5/20 日估算流量、覆盖率和滚动历史百分位；
- 沪深融资余额汇总、1/5/20 日变化和历史百分位；
- 可选的证券—主题映射，用于聚合主题融资证据；
- “多证据参与增强、配置型资金改善、杠杆主导活跃、成交情绪脉冲、多证据分歧、参与度收缩、数据不足”等中性状态；
- 支持证据、反向证据、未知项和后续确认条件；
- 原始快照、紧凑历史、结构化 JSON、Markdown 与静态 HTML；
- `live` 和隔离的 `mock` 模式；
- GitHub Actions CI、定时生成和 GitHub Pages 部署；
- Mihomo（Clash Meta 内核）代理订阅、节点健康检查与本地 SOCKS5 网关；
- AKShare 直连失败后，使用标准 Playwright 经本地 SOCKS5 获取东方财富 JSON；
- 数据源失效时发布“数据不足”，不会自动用演示数据伪装真实市场。

## 重要边界

- ETF 估算流量使用“份额变化 × 当日净值或 IOPV 代理”，不识别具体交易者身份。
- 融资余额描述杠杆交易资金敞口，不等同于机构资金。
- 成交额不称为净流入或净流出。
- M1 不提供北向日净额、衍生品、回购增减持或 Level-2 结论。
- 首次真实运行缺少历史数据，1/5/20 日指标和长期百分位会逐步形成；系统不会用 0 填充缺失值。

## 工程结构

```text
src/a_stock_radar/
  sources.py       # AKShare 实时适配、浏览器回退和演示数据源
  browser_fetcher.py # Playwright JSON 抓取与东方财富回退适配
  features.py      # 市场、ETF、融资特征
  states.py        # 规则状态和证据记录
  pipeline.py      # 端到端任务
  reporting.py     # Markdown、HTML、JSON
  templates/       # 日报与静态页面模板
config/            # 阈值、主题词典和数据源注册
metadata/          # 证券—主题映射
data/raw/          # 每次抓取的原始快照
data/history/      # 最近约 320 个交易日的紧凑历史
reports/           # 日报
site/              # GitHub Pages 发布目录
scripts/           # Mihomo 安装、配置和就绪检查
diagnostics/       # 运行失败截图、HTML、代理日志（不提交 Git）
runtime/           # Mihomo 二进制、配置和缓存（不提交 Git）
```

`mock_*` 和 `live_*` 历史文件完全隔离，先运行演示模式不会污染真实历史。

## 本地运行

要求 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,browser]'
python -m playwright install chromium
pytest -q
```

生成演示日报：

```bash
python -m a_stock_radar.cli run \
  --date 2026-07-17 \
  --stage confirmed \
  --data-mode mock
```

生成真实日报：

```bash
python -m a_stock_radar.cli run \
  --stage confirmed \
  --data-mode live
```

输出：

```text
site/index.html
site/report.md
site/api/v3/latest.json
site/api/v3/market-state.json
site/api/v3/sector-states.json
site/api/v3/source-quality.json
reports/latest/latest.md
reports/latest/latest.json
```

本地预览：

```bash
python -m http.server 8000 --directory site
```

打开 `http://localhost:8000`。


## Clash/Mihomo 浏览器代理链路

真实模式的网络路径是：

```text
mergelist 订阅
  → Mihomo 加载代理节点并健康检查
  → 本地 SOCKS5 127.0.0.1:7891
  → Playwright Chromium
  → 东方财富公开 JSON 接口
```

Python 不直接解析或轮换远端节点。Mihomo 的 `RADAR-AUTO` 策略组自动选择当前可用节点，Playwright 始终只连接本地 SOCKS5。AKShare 仍作为首选；只有 `stock_zh_a_spot_em` 或 `fund_etf_spot_em` 失败或返回空数据时，才启动浏览器回退。

GitHub Actions 会自动完成：

1. 下载固定版本的 Mihomo；
2. 以 `https://mergelist.vercel.app/api/all` 建立远程 `proxy-provider`；
3. 在 `127.0.0.1:7891` 暴露 SOCKS5；
4. 检查控制器、代理出口和目标站点；
5. 安装 Playwright Chromium；
6. 运行真实数据抓取；
7. 将代理日志、浏览器截图和失败页面保存为 Actions Artifact。

可在仓库 `Settings → Secrets and variables → Actions → Variables` 配置：

| Variable | 默认值 | 用途 |
|---|---|---|
| `MIHOMO_PROVIDER_URL` | `https://mergelist.vercel.app/api/all` | Clash/Mihomo 订阅地址 |
| `MIHOMO_VERSION` | `v1.19.28` | Mihomo 固定版本 |
| `MIHOMO_HEALTHCHECK_URL` | `https://quote.eastmoney.com/` | 节点健康检查目标 |

订阅返回内容需要是 Mihomo/Clash 可识别的代理订阅或 `proxy-provider` 内容。无法解析时，`fetch-diagnostics-*` Artifact 内的 `mihomo.log` 会显示具体错误。

### 本地启动代理链路

```bash
python -m pip install -e '.[dev,browser]'
python -m playwright install chromium

MIHOMO_PROVIDER_URL=https://mergelist.vercel.app/api/all \
  ./scripts/install_mihomo.sh

python scripts/render_mihomo_config.py

./runtime/mihomo/bin/mihomo \
  -d runtime/mihomo \
  -f runtime/mihomo/config.yaml \
  > diagnostics/mihomo.log 2>&1 &

python scripts/wait_for_mihomo.py

RADAR_BROWSER_FALLBACK=true \
RADAR_BROWSER_PROXY=socks5://127.0.0.1:7891 \
ALL_PROXY=socks5h://127.0.0.1:7891 \
HTTP_PROXY=http://127.0.0.1:7890 \
HTTPS_PROXY=http://127.0.0.1:7890 \
python -m a_stock_radar.cli run --stage confirmed --data-mode live
```

浏览器回退失败时会在 `diagnostics/browser/` 保存截图和 HTML。真实报告继续生成，并把对应来源标记为缺失，而不是填入模拟数据。

## GitHub 部署

1. 新建 GitHub 仓库并上传本目录全部内容。
2. 在仓库 `Settings → Pages` 中，把 Source 设为 **GitHub Actions**。
3. 在 `Actions` 中先运行 `CI`。
4. 手动运行 `Build and deploy radar`，第一次建议选择 `mock`，确认页面部署正常。
5. 再手动运行一次 `live`。真实来源不可用时，页面会展示缺失来源和“数据不足”。
6. 工作流默认在北京时间工作日 20:30 生成初版，23:15 生成确认版。真实模式会先启动 Mihomo 本地 SOCKS5，再执行抓取。

工作流会把紧凑历史和日报 JSON 提交回仓库，把每次原始快照保存为保留 30 天的 Actions Artifact，并直接上传 `site/` 作为 Pages artifact。

### 仓库权限

工作流需要：

```text
contents: write
pages: write
id-token: write
```

在组织仓库中，还要确认 Actions 允许 `GITHUB_TOKEN` 写入仓库。

## 主题与融资映射

ETF 使用 `config/sector_taxonomy.yaml` 中的名称规则归入主题组。规则按顺序首次匹配。

融资明细只有在 `metadata/security_sector_map.csv` 存在映射时才进入主题证据：

```csv
security_code,theme_id,theme_name
688981,semiconductor,半导体与芯片
300750,new_energy,新能源
```

示例映射仅用于演示工程结构，不是一套完整、可回溯的行业分类。正式运行时应替换为带版本日期的申万、中信或自有分类映射。没有映射的融资数据只用于全市场状态，不会硬归因到板块。

## 数据来源适配

当前实时适配通过 AKShare 调用：

- `stock_zh_a_spot_em`
- `fund_etf_spot_em`
- `fund_etf_scale_sse`
- `fund_scale_daily_szse`
- `stock_margin_sse`
- `stock_margin_szse`
- `stock_margin_detail_sse`
- `stock_margin_detail_szse`

其中 ETF 份额和融资融券的原始目标来源是沪深交易所；行情和 IOPV 代理包含聚合来源。所有调用均独立捕获异常并生成来源质量记录。东方财富两项聚合接口在 AKShare 失败后可通过 Playwright＋Mihomo SOCKS5 回退；交易所 ETF 份额和融资接口仍保持 AKShare 独立抓取与显式降级。

## 初次上线建议

### 第1阶段：验证部署

- 使用 `mock`；
- 检查 Pages、JSON、Markdown、CI 和提交权限；
- 确认页面醒目标注“演示数据”。

### 第2阶段：积累真实历史

- 切换到 `live`；
- 每天保留官方 ETF 份额和融资余额；
- 在 5 个交易日后启用短期变化；
- 在 20 个交易日后观察中期变化；
- 在至少 60 个有效样本后显示历史百分位。

### 第3阶段：完善板块映射

- 建立 point-in-time 证券分类文件；
- 为映射增加 `effective_from`、`effective_to` 和 `taxonomy_version`；
- 避免用今天的行业分类回填历史。

## 数据故障处理

- 单个来源失败不会终止整个任务；
- 缺失数据不会填为 0；
- 当市场或 L1 数据不足时，状态降级；
- 真实模式不会自动切换到演示模式；
- 可在 `site/api/v3/source-quality.json` 查看来源错误；
- 同一天重复运行会按日期和实体键覆盖，不会重复追加。

## 测试

```bash
pytest -q
ruff check src tests scripts
```

测试覆盖：

- 完整演示流水线；
- 页面和 JSON 生成；
- 演示与真实历史隔离；
- 历史百分位最低样本；
- 主题映射；
- 日报禁用表达和风险声明。

## 后续 M1.1

建议下一步增加：

- 交易所交易日历和节假日严格判断；
- ETF 跟踪指数主数据，替代单纯名称匹配；
- ETF 份额拆分、合并、新上市和清盘异常识别；
- 按日期版本化的证券—行业映射；
- 初版、确认版原始快照并存；
- 对象存储接口，逐步将原始快照移出 Git 仓库；
- 数据源重试、代理和固定出口 IP 支持。

## 免责声明

本项目仅用于学习、技术研究和市场复盘。数据可能延迟、修订、中断或存在授权限制；商业使用前应核查数据许可和再分发条款。系统输出不构成投资建议。

## 从发布 ZIP 自动更新现有仓库

发布包包含：

```text
scripts/update_workspace.py
scripts/update_workspace.sh
```

脚本用于把新发布包完整替换到已有 Git 工作区，同时：

- 永远保留目标仓库的 `.git/`；
- 合并并保留现有 `reports/`；
- 合并并保留现有 `data/history/`，避免滚动历史丢失；
- 保留本地 `.env`、`.env.local` 等环境文件；
- 删除旧版本中已经不存在的代码文件；
- 更新后运行 `compileall`，并在工具已安装时运行 `pytest` 和 `ruff`；
- 自动执行 `git add -A`、`git commit` 和 `git push`；
- 校验或复制失败时自动恢复更新前的工作区。

推荐将发布 ZIP 解压到目标仓库之外，例如：

```bash
unzip a_stock_evidence_radar_m1_clash_fixed.zip -d /tmp/radar-release

/tmp/radar-release/a_stock_evidence_radar_m1_clash_fixed/install_release.sh \
  /workspaces/a-stock-evidence-radar
```

`install_release.sh` 是最简单的入口；后续参数会原样传给 Python 更新器。

如果 ZIP 解压后没有外层目录，则使用：

```bash
/tmp/radar-release/scripts/update_workspace.sh \
  --workspace /workspaces/a-stock-evidence-radar
```

默认要求目标仓库没有未提交修改。确实需要覆盖未提交内容时：

```bash
./scripts/update_workspace.sh \
  --workspace /workspaces/a-stock-evidence-radar \
  --allow-dirty
```

先验证但不修改：

```bash
./scripts/update_workspace.sh \
  --workspace /workspaces/a-stock-evidence-radar \
  --dry-run
```

只提交、不推送：

```bash
./scripts/update_workspace.sh \
  --workspace /workspaces/a-stock-evidence-radar \
  --no-push
```

指定提交信息：

```bash
./scripts/update_workspace.sh \
  --workspace /workspaces/a-stock-evidence-radar \
  --message "fix: repair Mihomo provider bootstrap"
```

也可以让脚本直接读取 ZIP，但需要从现有脚本副本运行：

```bash
python scripts/update_workspace.py \
  --archive /tmp/a_stock_evidence_radar_m1_clash_fixed.zip \
  --workspace /workspaces/a-stock-evidence-radar
```

在 Codespaces 中，GitHub 通常已经配置好 `origin` 和登录凭据。若推送失败，本地提交仍会保留，修复认证或分支保护后重新执行 `git push` 即可。

### 安装校验选项

如目标环境的 Ruff 版本或本地配置临时冲突，可以仅跳过 lint：

```bash
./install_release.sh /path/to/repo --skip-lint
```

这不会跳过 Python 编译和 pytest；正式 CI 仍会执行仓库内配置的 Ruff 规则。
