# -*- coding: utf-8 -*-
"""
渠道：企业官网招聘页（阶段一·公开渠道）
=======================================
抓取"成都本地重点企业 + 用户关注企业"官网的公开招聘页/公告。
策略：维护一份企业招聘页 URL 清单（CONFIG），逐站抓取公告列表；
      配置可在本文件顶部增删（企业官网结构各异，单个站点失败不影响整体）。
说明：企业官网无统一标准，本渠道以"公告标题+链接"为主，
      详情页如结构简单（纯静态文本）则一并抓取正文作 JD 摘要。
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

CHANNEL = "企业官网"

# (名称, 招聘页URL, 公司字段, 是否成都本地)
CONFIG = [
    ("西瓜创客", "https://xigua.zhiye.com/", "西瓜创客(成都娄外科技)", True),   # 用户重点跟进（教培双休）；智联招聘官网托管
    ("成都农商银行", "https://www.cdrcb.com/pin/", "成都农商银行", True),        # 2026-10-28 有科技岗/产业金融岗新公告
    ("成都产业集团", "https://www.cdii.com.cn/", "成都产业集团", True),
    ("四川能投", "https://www.scnyw.com/", "四川能投集团", True),
]

SKIP_WORDS = ("首页", "登录", "注册", "联系我们", "关于", "诚聘英才首页", "网站地图",
              "员工招聘", "加入我们", "人才招聘", "招聘公告", "社会招聘", "校园招聘",
              "许可证公告", "招聘流程", "人力资源", "人才理念", "招聘动态")
# 说明：纯导航词（员工招聘/加入我们等）不算岗位，需带具体标题才收录；
#      成都农商银行公告列表为 JS 渲染，纯 HTTP 受限，阶段二浏览器登录态解决。


def fetch_one(name, url, company, local):
    jobs = []
    html = common.http_get(url, retries=1, ssl_ok=True, timeout=20)
    links = common.extract_links(html, url)
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 4:
            continue
        if not any(k in t for k in ("招聘", "校招", "社会招聘", "加入我们", "诚聘", "人才", "岗位", "招募", "管培", "公告")):
            continue
        if any(k in t for k in SKIP_WORDS):
            continue
        # 详情页是本站招聘公告时抓正文作 JD 摘要
        jd = ""
        if href.startswith(url) or ("pin/" in href or "zhiye.com" in href):
            try:
                det = common.http_get(href, retries=0, ssl_ok=True, timeout=15)
                jd = common.strip_html(det)[:600]
            except Exception:
                jd = ""
        jobs.append({
            "职位名": t[:60],
            "公司": company,
            "薪资": "按企业公告（需进详情页）",
            "地点": "成都（%s）" % ("本地企业" if local else "见公告"),
            "来源": "企业官网-%s" % name,
            "作息": "未注明",
            "工作地址": "见公告",
            "链接": href,
            "JD摘要": jd or ("%s官网招聘公告。" % name),
            "外包属性": "企业直招（以公告为准）",
            "备注": "抓取自%s官网招聘页；岗位明细与投递入口见公告正文" % name,
        })
    return jobs


def fetch():
    out = []
    for name, url, company, local in CONFIG:
        try:
            jobs = fetch_one(name, url, company, local)
            if not jobs:
                print("[%s] %s 无招聘公告链接（可能官网结构变化，记录受限）" % (CHANNEL, name))
            out.extend(jobs)
        except Exception as e:
            print("[%s] %s 受限: %s" % (CHANNEL, name, str(e)[:120]))
    return out


if __name__ == "__main__":
    jobs = fetch()
    print("企业官网渠道抓取 %d 条" % len(jobs))
    for j in jobs[:10]:
        print(" -", j["职位名"][:40], "|", j["公司"])
