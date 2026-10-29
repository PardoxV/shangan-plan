# 规则模板指南（RULES_GUIDE）

## 一句话

规则是「上岸计划」的大脑：**它决定什么岗位会出现在你的推送里，什么不会。**
仓库提供两层规则文件：

| 文件 | 角色 | 给谁看 |
|---|---|---|
| `workbench/rules-template.json` | **面向非技术用户的规则模板**（含逐项填写说明） | 你、你的朋友 |
| `agent/rules.json` | 规则引擎实际读取的完整规则（v5.2 示例，已脱敏） | 引擎、技术用户 |

## 模板怎么用

1. 把 `workbench/rules-template.json` 复制一份，改名 `rules.json`
2. 逐项填写（模板内每个字段都带中文说明）：

| 模块 | 含义 | 示例 |
|---|---|---|
| `salary_rule` | 可接受薪资区间 | `tax_pretax_ok_range: "5-7K"`、`not_below: 4000` |
| `commute_rule` | 家位置 + 通勤上限 | 骑行 ≤30 分钟、公交 ≤40 分钟 |
| `worktime_rule` | 作息偏好与排除 | 接受双休/大小周；排除轮休/夜班 |
| `match_rules` | 岗位方向匹配 | high: AI训练师/数据标注；never: 纯开发 |
| `excluded_job_types` | 岗位类型硬排除 | 客服/主播/销售/外卖… |
| `outsourcing_blacklist` | 外包公司黑名单（**最高优先级**） | 软通/法本/人瑞/首聘… |
| `hard_redlines` | 其他红线 | 已关闭岗不推、外包不推、无经验门槛优先 |

3. 把填写好的 `rules.json` 放回 `agent/`，引擎自动读取

## 完整说明

`workbench/规则模板使用说明.md` 是模板的配套使用说明（已随仓库分发），
包含字段明细、导出/导入方式与常见问题。

## 示例值说明

`agent/rules.json` 中的 `YOUR_*` 与近似坐标（如 `104.0, 30.5`）均为占位，
**必须替换为你自己的值**后规则才有效。
