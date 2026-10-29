# -*- coding: utf-8 -*-
"""
渠道：高校就业信息网（阶段一·公开渠道）
=======================================
来源站点：
  1. 四川大学就业指导中心（jy.scu.edu.cn）
  2. 电子科技大学就业网（jiuye.uestc.edu.cn）
  3. 西南交通大学就业指导中心（jiuye.swjtu.edu.cn）

各校招聘公告列表 → 统一 schema。公告多为"2027届校招/双选会/宣讲会"，
下游按用户画像（2025届应届生/成都/双休）过滤。
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

CHANNEL = "高校"

# 各校：入口页 + 详情页前缀 + 公司字段名（供摘要）
SCHOOLS = [
    {
        "name": "川大就业",
        "source": "高校-四川大学就业网",
        "index": "https://jy.scu.edu.cn/index/index/index.html",
        "detail_prefix": "https://jy.scu.edu.cn/index/index/newsdetail.html",
        "company": "四川大学就业网发布单位",
    },
    {
        "name": "电子科大就业",
        "source": "高校-电子科技大学就业网",
        "index": "https://jiuye.uestc.edu.cn/career/",
        "detail_prefix": "https://jiuye.uestc.edu.cn",
        "company": "电子科技大学就业网发布单位",
    },
    {
        "name": "西南交大就业",
        "source": "高校-西南交通大学就业网",
        "index": "https://jiuye.swjtu.edu.cn/career/index",
        "detail_prefix": "https://jiuye.swjtu.edu.cn",
        "company": "西南交通大学就业网发布单位",
    },
]

SKIP_WORDS = ("首页", "登录", "注册", "联系我们", "关于我们", "下载中心", "服务指南",
              "毕业生数据", "学习园地", "机构设置", "教师登录", "学生登录", "单位登录",
              "招聘会邀请函", "邀请函", "重置密码", "服务安排")


def fetch_school(sch):
    jobs = []
    html = common.http_get(sch["index"], retries=1)
    links = common.extract_links(html, sch["index"])
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 6:
            continue
        if any(k in t for k in SKIP_WORDS):
            continue
        # 详情页判定：本站详情链接或外部校招/招聘页
        is_detail = (href.startswith(sch["detail_prefix"])
                     and ("newsdetail" in href or "career" in href or "content" in href))
        is_outer = (("campus." in href or "zhaopin" in href or "job" in href.lower())
                    and href.startswith("http"))
        if not (is_detail or is_outer):
            continue
        # 保留含招聘信号的公告
        if not any(k in t for k in ("招聘", "校招", "双选", "宣讲", "实习", "管培", "招募", "邀请函")):
            continue
        jobs.append({
            "职位名": t[:70],
            "公司": sch["company"],
            "薪资": "按公告（校招多为面议/标准薪资）",
            "地点": "视单位而定（成都本地优先，需读公告）",
            "来源": sch["source"],
            "作息": "未注明",
            "工作地址": "见公告（投递前确认是否成都岗）",
            "链接": href,
            "JD摘要": "高校就业网招聘公告（校招/双选会/宣讲会/实习）。",
            "外包属性": "",
            "备注": "抓取自%s；是否成都岗位、专业门槛需进公告确认（2025届可投与否以公告为准）" % sch["name"],
        })
    return jobs


def fetch():
    out = []
    for sch in SCHOOLS:
        try:
            out.extend(fetch_school(sch))
        except Exception as e:
            print("[%s] %s 受限: %s" % (CHANNEL, sch["name"], str(e)[:120]))
    return out


if __name__ == "__main__":
    jobs = fetch()
    print("高校渠道抓取 %d 条" % len(jobs))
    for j in jobs[:10]:
        print(" -", j["职位名"][:40], "|", j["来源"])
