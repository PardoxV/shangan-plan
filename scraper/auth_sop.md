# 登录态常态化 SOP（auth_guard.py 配套）

## 平台台账
| 平台 | 账号key | 登录页 | 预估有效期 | 风控强度 |
|---|---|---|---|---|
| 智联招聘 | zhaopin | https://passport.zhaopin.com/login | 约20-40天 | 中 |
| 前程无忧51job | 51job | https://login.51job.com/login.php | 约20-40天 | 中 |
| BOSS直聘 | boss | https://www.zhipin.com/web/user/?ka=header-login | 约5-10天 | 极强（设备指纹+滑块+行为识别） |
| 猎聘 | liepin | https://passport.liepin.com/account/login | 约10-20天 | 较强 |

> 有效期均为「管理台账预估」非官方数据，以实际失效为准。

## 首次登录（一次性）
1. 浏览器固定 profile：抓取专用浏览器固定同一用户目录（如 D:\job-agent\browser-profile），登录态落盘
2. 打开登录页 → 手机扫码/账密登录（建议与日常账号分开）
3. 登录后打开个人中心确认已登录
4. 运行：python auth_guard.py login zhaopin （登记台账）

## 每日（自动，已接入推送任务）
- 推送任务第〇步A运行后，检查 auth_guard.py alert 输出：
  - 无告警 → 平台渠道可抓
  - 有过期/临期 → 该渠道停用（拦截即停），公开渠道不受影响
- 飞书连接器关闭期间告警仅落本地，恢复后在推送汇报附带

## 每周保活（真人行为，延长会话寿命）
- 每周打开已登录平台个人中心页浏览1-2分钟（看个人中心/翻几页岗位）
- 频率：智联/51job 每2-3周一次；BOSS 每周一次
- 不要高频无人值守抓取：单次会话限时、随机延时，模拟真人

## 重新登录（失效后恢复）
1. auth_guard.py alert 提示某平台过期
2. 打开该平台登录页重新扫码（同一浏览器/profile）
3. 运行：python auth_guard.py login <平台key>
4. 次日推送任务自动恢复该平台渠道
