# -*- coding: utf-8 -*-
"""
渠道：应届生招聘网（阶段一·公开渠道）
=======================================
来源：
  1. 应届生求职网（yingjiesheng.com）——校招/实习公告聚合，成都分站
  2. 应届生 Q 站搜索（q.yingjiesheng.com）——有 WAF 防护，纯 HTTP 受限，
     记录受限原因，阶段二用浏览器登录态解决

说明：yingjiesheng.com 主页是公告聚合（campus.51job 等外部链接为主）；
      成都分站首页纯 HTTP 返回空（JS 渲染），故本渠道以主页公告+成都链接为主。
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

CHANNEL = "应届生网"


def fetch_yjs_home():
    jobs = []
    url = "https://www.yingjiesheng.com/"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 6:
            continue
        if not any(k in t for k in ("招聘", "校招", "实习", "管培", "2026届", "2027届", "应届")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "行业招聘", "关于")):
            continue
        # 应届生主页大量外部校招页链接（campus.51job.com 等）
        if not (href.startswith("http") and any(dom in href for dom in
                ("campus.", "zhiye.com", "iguopin.com", "yingjiesheng.com", "51job"))):
            continue
        jobs.append({
            "职位名": t[:70],
            "公司": "应届生求职网发布单位",
            "薪资": "按公告",
            "地点": "见公告（成都相关岗位优先）",
            "来源": "应届生网-%s" % (t[:10]),
            "作息": "未注明",
            "工作地址": "见公告",
            "链接": href,
            "JD摘要": "应届生求职网校招/实习公告。",
            "外包属性": "",
            "备注": "抓取自应届生求职网主页公告；是否成都岗/2025届可投以公告为准",
        })
    return jobs


def fetch_q_search():
    """Q站搜索：有 WAF（_waf_ cookie），纯 HTTP 返回加密 JS，记录受限。"""
    try:
        html = common.http_get("https://q.yingjiesheng.com/jobs/search/?jobarea=090200", retries=0)
        if "waf" in html[:500].lower() or html.startswith("{"):
            raise RuntimeError("Q站 WAF 拦截（需浏览器登录态，阶段二处理）")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("Q站访问失败: %s" % str(e)[:80])
    return []


def fetch():
    out = []
    try:
        out.extend(fetch_yjs_home())
    except Exception as e:
        print("[%s] 主页受限: %s" % (CHANNEL, str(e)[:120]))
    try:
        out.extend(fetch_q_search())
    except Exception as e:
        print("[%s] Q站受限（如实标注，阶段二浏览器登录态解决）: %s" % (CHANNEL, str(e)[:120]))
    return out


if __name__ == "__main__":
    jobs = fetch()
    print("应届生网渠道抓取 %d 条" % len(jobs))
    for j in jobs[:10]:
        print(" -", j["职位名"][:40], "|", j["来源"])
