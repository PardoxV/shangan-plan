# 求职Agent · 规则配置化工程

把「求职Agent每日岗位推送」的规则体系从"定时任务描述里的一段长文本"重构为
**可审计的配置文件 + 确定性过滤代码**（code as policy）。改规则只改文件，不碰任务描述。

## 目录结构

```
job-agent/
├── rules.json        # ★ 规则唯一权威（v3.0）：全部过滤/推送/跟进规则
├── filter.py         # ★ 确定性过滤引擎：把 rules.json 翻译为可复现判定
├── filter_report.json# 最近一次过滤运行的判定明细报告（可回溯）
├── db.py             # ★ 统一实体模型（SQLite）：jobs/companies/feedback 三表
├── jobs.db           # 本地数据库（权威表=飞书多维表格的本地投影）
├── sync_bitable.py   # 多维表格 → SQLite 全量对齐（与用户看到的同一份数据）
├── stats.py          # ★ 评测指标引擎：漏斗/分布/复推池/反馈回流
├── stats_report.json # 最近一次评测快照
└── README.md         # 本文件
```

## 分工边界（关键设计）

| 层 | 负责 | 谁执行 |
|---|---|---|
| **确定性判定** | 外包黑名单、岗位性质排除、薪资区间解析、作息关键词、通勤标记提取、匹配度关键词初判 | `filter.py`（代码） |
| **语义判断** | JD 匹配度复核、薪资市场价二审、备注撰写、边缘案例决策 | LLM（定时任务触发后的 Agent） |
| **数据源** | 岗位数据、通勤实测、时效验证、增量去重 | 定时任务执行流程 |

确定性规则保证"同样输入永远同样输出"；LLM 只在规则留白处做判断，
且每次判断的依据要求记入备注（可回溯、可沉淀为规则）。

## 怎么改规则

**只改 `rules.json`，不要改定时任务描述。** 常见修改：

- 加一家外包公司 → `outsource_blacklist.companies` 追加名称
- 调整通勤时间 → `commute.pass_any_of` 修改 max_min
- 加排除岗位 → `exclude_roles.keywords` 追加关键词
- 调薪资线 → `salary` 下修改 min/preferred/max
- 改推送条数/复推规则 → `daily_push` 下修改

改完执行一次 `filter.py` 验证效果（见下）。

## 怎么运行验证

```powershell
cd <PROJECT_ROOT>\job-agent

# 用历史岗位数据跑全量判定（数据支持多维表格ndjson 或 pushed_jobs.json）
python filter.py --data "<PROJECT_ROOT>\jobs_data\base_final_commute.ndjson" --summary

# 输出报告到指定位置
python filter.py --data <数据文件> --out <报告路径>
```

输出含义：
- `pushable=yes`：全部硬规则通过，可推送
- `pushable=downgrade`：有存疑项（如薪资存疑），降级但不拒绝，LLM 可复核恢复
- `pushable=no`：命中硬性排除（外包/岗位性质/薪资不达标/作息排除/通勤超圈）
- `pushable=needs_measure`：仅缺通勤实测，需高德测完再判

## 数据层与评测（短板2+3的落地）

```powershell
# 1) 本地实体模型初始化/刷新（从历史快照回填，含推送日期与匹配度）
python db.py init

# 2) 与飞书多维表格对齐（用户改过投递状态后运行，拉取权威全量）
python sync_bitable.py

# 3) 评测指标（漏斗/分布/复推池/反馈回流）
python stats.py
```

- 数据流向：**飞书多维表格（权威，用户可改）→ sync_bitable.py → SQLite（计算层）→ stats.py（指标）**
- jobs 表唯一键 `(title, company)` 保证跨日零重合可机械校验
- 用户反馈（合适/不合适/已投等）写入 `feedback` 表，攒够样本后回流推送排序（高命中方向提权）
- 定时任务每天推送入库后会自动跑 `stats.py` 刷新指标，周报可直接取数

## 与定时任务的关系

定时任务（每天10点，本地电脑）执行第一步即读取本目录 `rules.json` 作为规则权威，
再按 `filter.py` 做确定性过滤；推送入库后运行 `stats.py` 刷新评测指标。
任一环节缺失都会如实报告，不会静默降级。

## 已知权衡（设计时确认过的）

1. **薪资区间比 >1.5 即标存疑**：标注/训练类岗位区间天然偏宽，会误标较多"存疑"。
   处理：存疑仅是降级（downgrade）不是拒绝，LLM 按市场常识复核后可在备注写明依据并恢复推荐。
2. **黑名单按公司名+备注代发双重匹配**：招聘方代发（如 MiniMax 由怡卓人力代发）在备注中命中同样排除。
3. **通勤未实测=不推送**：确定性引擎对无实测标记的岗位返回 needs_measure，必须高德实测后才可进入推送。
4. **本地运行边界**：定时任务依赖本机开机（短板4-云端化的前置条件是部署环境，当前本地够用）。
