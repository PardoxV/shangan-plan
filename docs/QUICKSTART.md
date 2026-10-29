# 快速开始（QUICKSTART）

本文面向「想自己跑起来」的使用者。全流程分三档：**Demo 档（零配置）→ 单机档（真实通勤）→ 全链档（自动抓取+推送）**。

## 环境要求

- Python 3.10+（Windows / macOS / Linux 均可）
- 可选：飞书（岗位库与卡片推送）、高德开放平台账号（通勤实测）、招聘平台账号（平台渠道）

## 第一步：跑 Demo（零配置，5 分钟）

仓库自带的 `samples/golden.example.json` 是脱敏后的规则回归用例，含 20+ 条岗位样本。

```bash
cd agent
pip install -r requirements.txt 2>nul   # 无依赖或安装失败可跳过
python filter.py --data ../samples/golden.example.json --summary
```

预期输出：岗位经过「规则引擎 v5.2」过滤后，按推荐优先级给出清单与排除原因。

## 第二步：配你的规则（10 分钟）

1. 打开 `workbench/rules-template.json`，这是**面向非技术用户**的模板（含每项的填写说明）
2. 复制一份为 `rules.json`，按你的情况填：城市、通勤上限（骑行/公交分钟数）、薪资区间、
   作息偏好（双休/大小周…）、岗位方向（高/中/低匹配关键词）、外包黑名单、投递红线
3. 详细字段说明见 [RULES_GUIDE.md](RULES_GUIDE.md) 与 `workbench/规则模板使用说明.md`

## 第三步：接真实数据（30 分钟）

### 3.1 飞书多维表格（岗位库 + 卡片推送，可选）

1. 飞书 → 多维表格 → 新建「岗位库」表，字段参考 `agent/config.json` 中的 `bitable` 配置
2. 把 `agent/config.example.json` 复制为 `agent/config.json`，填入你的：

| 配置项 | 位置 | 说明 |
|---|---|---|
| `target_open_id` | `push` 段 | 飞书卡片接收人 open_id |
| `base_token` / `table_id` | `bitable` 段 | 岗位库多维表格 |
| `web_service_key` | `amap` 段 | 高德 Web 服务 Key（通勤实测） |

> 本仓库所有脚本中的 `YOUR_*` 占位符即上述配置项，全局替换成你的值即可。

### 3.2 高德通勤实测（可选）

`agent/commute.py` 读取 `rules.json` 中的 `origin` 坐标与候选岗位地址，调用高德 API 实测
骑行/公交/地铁耗时，不达标的岗位标记为「通勤不达标」并降级。

### 3.3 招聘平台登录态（可选）

- 公开渠道（政企/高校/应届生/公众号/企业官网）**不需要登录**
- 平台渠道（智联/51job/BOSS/猎聘）需要登录态：在浏览器登录对应平台后，
  运行 `scraper/auth_guard.py login <平台>` 登记台账；登录态失效时该渠道自动跳过并如实标注
- 登录 SOP 见 `scraper/auth_sop.md`

## 第四步：跑完整流水线（每日自动）

```bash
# 手动触发一次完整链路（公开渠道抓取 → 详情解析 → 规则过滤 → 通勤实测 → 写表 → 发卡）
cd scraper && python run_scraper.py
cd ../agent && python push_pipeline.py --write --verify --summary
```

自动调度（每天 07:30 / 14:30 推送、补推检查、每周复盘）请在你的 Agent / 任务调度平台
中按本仓库文档配置；详见 `agent/每日链路操作手册.md`。

## 常见问题

| 现象 | 处理 |
|---|---|
| 平台渠道一条都没有 | 登录态过期 → `auth_guard.py status` 查看，重新登录后登记 |
| 通勤全不达标 | 检查 `rules.json` 的 `origin.geo` 是否填成了你的真实坐标（示例值 104.0, 30.5 必须替换） |
| 卡片发不出去 | 确认 `config.json` 的 open_id 与飞书权限；或先只用本地工作台看结果 |
| 想先看界面 | `cd workbench && python server.py` → 浏览器打开 http://localhost:8123 |
