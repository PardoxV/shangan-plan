# -*- coding: utf-8 -*-
"""
auth_guard.py - 登录态看门狗 v1.0
====================================
解决「平台登录态常态化」三件事中的两件：失效感知 + 恢复登记。
配合固定浏览器 profile（持久化会话）+ 每周保活（真人访问），构成完整闭环。

用法：
  python auth_guard.py status                 # 查看各平台登录态台账
  python auth_guard.py login <platform>       # 扫码登录成功后登记（platform: zhaopin/51job/boss/liepin）
  python auth_guard.py alert                  # 输出过期/临期告警（供推送汇报引用）
  python auth_guard.py bootstrap <platform>   # 首次登录引导（打印操作步骤）

平台有效期说明：以下为「管理台账预估」而非官方数据，以实际失效为准——
  智联/51job 通常可维持 20-40 天；BOSS 直聘风控强，约 5-10 天即可能要求重新验证；
  猎聘 10-20 天。到期或临期 → 重新扫码登录一次即可，Cookie 写入固定 profile 目录后复用。
"""
import json
import sys
import os
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "auth_log.json")
SOP_FILE = os.path.join(BASE_DIR, "auth_sop.md")

# 平台台账：有效期预估（天），按风控强度保守取值
PLATFORMS = {
    "zhaopin": {"name": "智联招聘", "ttl_days": 30, "login_url": "https://passport.zhaopin.com/login", "home_url": "https://www.zhaopin.com"},
    "51job":   {"name": "前程无忧51job", "ttl_days": 30, "login_url": "https://login.51job.com/login.php", "home_url": "https://www.51job.com"},
    "boss":    {"name": "BOSS直聘", "ttl_days": 7,  "login_url": "https://www.zhipin.com/web/user/?ka=header-login", "home_url": "https://www.zhipin.com"},
    "liepin":  {"name": "猎聘", "ttl_days": 14, "login_url": "https://passport.liepin.com/account/login", "home_url": "https://www.liepin.com"},
}

# 建议：抓取浏览器固定使用同一 profile 目录（持久化会话），登录一次长期复用。
PROFILE_HINT = (
    "提示：请在浏览器设置中将抓取专用 profile 固定到同一目录（如 D:\\job-agent\\browser-profile），"
    "扫码登录后 Cookie/设备指纹落盘，后续抓取复用同一会话。"
)


def load_log():
    if not os.path.exists(LOG_FILE):
        return {}
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_log(log):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def today():
    return date.today()


def status():
    log = load_log()
    lines = []
    lines.append("=== 登录态台账（%s） ===" % today())
    for key, p in PLATFORMS.items():
        rec = log.get(key)
        if not rec or "last_login" not in rec:
            lines.append("  %-12s %-10s 【未登记】→ 需首次扫码登录" % (p["name"], key))
            continue
        last = rec["last_login"]
        try:
            last_d = date.fromisoformat(last)
        except Exception:
            lines.append("  %-12s %-10s 【台账异常】last_login=%s" % (p["name"], key, last))
            continue
        expire = last_d + timedelta(days=p["ttl_days"])
        remain = (expire - today()).days
        if remain < 0:
            st = "【已过期 %d 天】→ 请重新登录" % (-remain)
        elif remain <= 3:
            st = "【临期 %d 天】→ 尽快保活/重登" % remain
        else:
            st = "【有效】剩 %d 天（到期 %s）" % (remain, expire)
        lines.append("  %-12s %-10s %s" % (p["name"], key, st))
    lines.append("")
    lines.append(PROFILE_HINT)
    lines.append("保活建议：每周打开已登录平台个人中心页浏览 1-2 分钟（真人行为），可显著延长会话寿命。")
    print("\n".join(lines))


def login(platform):
    if platform not in PLATFORMS:
        print("未知平台：%s。可用：%s" % (platform, "/".join(PLATFORMS.keys())))
        return 1
    log = load_log()
    log[platform] = {"last_login": today().isoformat(),
                     "expires": (today() + timedelta(days=PLATFORMS[platform]["ttl_days"])).isoformat(),
                     "note": "扫码登录登记"}
    save_log(log)
    p = PLATFORMS[platform]
    print("已登记 %s 登录时间=%s，预估到期=%s（台账预估，实际以平台失效为准）" %
          (p["name"], today().isoformat(), log[platform]["expires"]))
    print("请确认浏览器固定 profile 已保存该平台登录态；否则下次抓取仍会失效。")
    return 0


def alert():
    log = load_log()
    warns = []
    for key, p in PLATFORMS.items():
        rec = log.get(key)
        if not rec or "last_login" not in rec:
            warns.append("【%s】未登记登录态，平台渠道抓取将受限（如需抓该平台请扫码登录）" % p["name"])
            continue
        try:
            last_d = date.fromisoformat(rec["last_login"])
        except Exception:
            warns.append("【%s】台账异常，需重新登记" % p["name"])
            continue
        remain = (last_d + timedelta(days=p["ttl_days"]) - today()).days
        if remain < 0:
            warns.append("【%s】登录态已过期 %d 天，该渠道已停用；重新扫码登录后运行 auth_guard.py login %s" %
                         (p["name"], -remain, key))
        elif remain <= 3:
            warns.append("【%s】登录态临期（剩 %d 天），建议尽快保活或重登" % (p["name"], remain))
    if warns:
        print("\n".join(warns))
    else:
        print("所有平台登录态均在有效期内。")
    print("告警备注：飞书连接器当前关闭，告警仅落本地；连接器恢复后可在推送汇报中附带本输出。")


def bootstrap(platform):
    if platform not in PLATFORMS:
        print("未知平台：%s" % platform)
        return 1
    p = PLATFORMS[platform]
    print("首次登录 %s 操作步骤：" % p["name"])
    print("  1. 用抓取专用浏览器（固定 profile）打开：%s" % p["login_url"])
    print("  2. 手机扫码 / 账密登录（建议与日常账号分开，接受平台风控风险）")
    print("  3. 登录成功后，打开个人中心确认已登录：%s" % p["home_url"])
    print("  4. 回到命令行运行：python auth_guard.py login %s" % platform)
    print("")
    print(PROFILE_HINT)


def main():
    if len(sys.argv) < 2:
        print("用法：python auth_guard.py status|login <平台>|alert|bootstrap <平台>")
        return 1
    cmd = sys.argv[1]
    if cmd == "status":
        status()
    elif cmd == "login" and len(sys.argv) >= 3:
        return login(sys.argv[2])
    elif cmd == "alert":
        alert()
    elif cmd == "bootstrap" and len(sys.argv) >= 3:
        return bootstrap(sys.argv[2])
    else:
        print("用法：python auth_guard.py status|login <平台>|alert|bootstrap <平台>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
