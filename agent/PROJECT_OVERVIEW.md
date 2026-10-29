# 上岸计划 · DeepSeek 交接说明

> 本文件是给接手 AI（DeepSeek）的项目入口，30 秒看懂全貌。

## 一句话定位
一套**个人 AI 求职自动化工作流系统**：按用户本人硬规则，每日自动从多来源抓取成都岗位、规则过滤、通勤实测、时效验证、去重后推送，并随投递反馈自动学习降权，已连续运行约 2 个月。

## 用户画像（规则的制定者）
- 求职者，25 届计算机本科（西南交大希望学院），居成都双流YOUR_HOME_ADDRESS
- 目标：月到手 ≥5000、公交通勤 ≤60 分钟、周末双休
- 明确排除：销售/客服/主播/服务员/外卖/纯体力/外呼/常出差；剪辑/设计/代码/CET4-6/1-2年经验等硬技能门槛不豁免不推
- 目标岗位方向：AI 训练师 / 数据标注 / AI 产品运营 / 大模型评测 / 教培双休岗 / 政企编外

## 系统三层架构
1. **规则层**：`rules.json` v5.2 —— 薪资/作息/通勤门槛、外包黑名单 46 家、skill_gate、反馈闭环规则
2. **数据管道**：平台四源（BOSS/智联/51job/猎聘）+ 非平台渠道（公众号/院校就业网/政企官网/企业官网/通用搜索）→ 规则过滤 → 高德通勤实测 → 逐链接时效验证 → 双键去重（title+company）
3. **反馈闭环**：投递状态追踪 → 婉拒公司/类别自动降权（`feedback_learn.py` → `exclusion_learned.json`）→ 未投高分岗复推池

## 关键文件索引
| 文件 | 作用 |
|---|---|
| `每日链路操作手册.md` | **权威运维手册**（7步链路+故障速查+防覆盖红线），先读这个 |
| `rules.json` | 规则唯一权威（v5.2） |
| `push_pipeline.py` | 推送编排引擎（engine 纯函数，可注入测试） |
| `feedback_learn.py` | 反馈学习（第〇步） |
| `filter.py` / `rerank.py` / `dedup` | 过滤/重排/去重 |
| `daily_20261024.json` ~ `daily_20261018.json` | 每日推送证据（pushed=验证有效数，勿覆盖） |
| `exclusion_learned.json` | 反馈学习产物（公司拉黑/类别排除/复推池46条） |
| `all_records_raw.json` / `jobs.db` | 岗位库全量投影（107条） |
| `run_metrics.py` / `stats.py` / `weekly_analysis.py` | 评测指标与周报 |
| `dump_all.py` / `sync_snapshot.py` / `rebuild_ui.py` | UI 工作台数据链与线上发布 |
| `求职者的简历_新版.docx` | 含"项目经历"栏的单页简历（本项目写入处） |
| `README.md` / `channels_health.json` | 渠道健康度 |

## 如何运行（每日7步）
```
python feedback_learn.py --dump-first          # 0.读反馈记忆
# 1.浏览器登录态自查 BOSS/智联/51job/猎聘
# 2-3.平台+非平台搜索
python push_pipeline.py --date YYYYMMDD --write --verify   # 4-6.过滤/通勤/时效/去重
# 7.写多维表格 + 发飞书卡片 + UI重建 + 评测
python dump_all.py && python sync_snapshot.py && python rebuild_ui.py --publish
python run_metrics.py
```

## 当前状态（截至 2026-10-26）
- 岗位库 107 条；已投 30（28%）、婉拒 9、未投 68；用户反馈学习 7 条
- 婉拒类别已自动降权：视频/Caption 方向 ×8、资深经验门槛 ×2、剪辑作品集 ×1
- 复推池 46 条未投高分岗（Top：成都人事考试网公招/天府新区编外/电子科大科研助理/星明未来AI运营/知道创宇研训师）
- **受限**：飞书 connector 当前关闭（写多维表格/发卡片链路停）；平台抓取需浏览器登录态，无人值守定时任务时受限

## 已知痛点（可让 AI 帮忙的方向）
1. 平台抓取依赖人工浏览器登录态，无登录态时每日推送常为 0
2. 复推池条目 URL 字段缺失，无法自动做时效验证
3. 非平台渠道（公众号/院校/政企）未自动化抓取
4. 岗位库字段：通勤分布全是 unmeasured、匹配度全是 other，历史数据未补标注
5. 工作台 UI 已上线（线上应用 YOUR_APP_ID），但本地 server.py 与线上数据链未完全打通
