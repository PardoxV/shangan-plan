# -*- coding: utf-8 -*-
"""
渠道：微信公众号文章（阶段一·公开渠道）
=======================================
策略：微信公众号文章（mp.weixin.qq.com/s/...）是公开网页，可直接抓取正文。

【阶段一受限说明（如实标注）】
  - 搜狗微信搜索（weixin.sogou.com）对纯 HTTP 返回无结果页（需浏览器 JS），
    本渠道当前无法自动"发现"公众号文章链接。
  - 因此本渠道以"人工维护的公开文章 URL 清单"运行：MANUAL_ARTICLES 可在
    _manual_update 提示下补充真实链接，脚本负责抓正文 + 提取岗位信息。
  - 公众号渠道的"内容源"已通过政企渠道的成都国企人才平台（gq.cdrchr.cn）
    和成都公共招聘网（cd.sc91.org.cn）间接覆盖（这些平台同步公众号招聘内容）。
  - 阶段二用豆包浏览器登录态 + 微信公众平台/搜狗微信页面抓取，可恢复自动发现。
"""
import sys, re, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

CHANNEL = "公众号"

# 人工维护的公众号公开文章 URL 清单（结构变化时在此增删）
MANUAL_ARTICLES = [
    # 占位：首次运行后由 run_manual_update 提示补充真实链接
]


def fetch_sogou(url):
    """搜狗微信搜索结果页 → mp.weixin.qq.com 文章链接。可能被验证码拦截。"""
    jobs = []
    html = common.http_get(url, retries=1)
    if "antispider" in html or "验证" in html[:2000]:
        raise RuntimeError("搜狗微信触发验证码拦截")
    for m in re.finditer(r'href=["\'](https://mp\.weixin\.qq\.com/s[^"\']+)["\']', html):
        link = m.group(1).replace("&amp;", "&")
        jobs.append(link)
    return jobs


def fetch_article(url):
    """抓取单篇公众号文章正文 → 岗位条目。"""
    html = common.http_get(url, retries=1)
    # 提取文章标题
    tm = re.search(r"<meta property=\"og:title\" content=\"([^\"]+)\"", html) or \
         re.search(r"<title>([^<]+)</title>", html)
    title = common.clean_title(tm.group(1)) if tm else ""
    if not title:
        return None
    text = common.strip_html(html)
    # 公众号正文容器
    body = text
    if not body or len(body) < 30:
        return None
    return {
        "职位名": title[:60],
        "公司": "公众号发布单位（详见正文）",
        "薪资": "按正文（常含薪资描述）",
        "地点": "成都（见正文）",
        "来源": "公众号-%s" % (title[:16] if len(title) > 4 else "微信文章"),
        "作息": "未注明",
        "工作地址": "见正文",
        "链接": url,
        "JD摘要": body[:600],
        "外包属性": "",
        "备注": "微信公众号公开文章抓取；是否岗位文、投递方式需读正文确认",
    }


def fetch():
    out = []
    # 1) 人工维护清单（搜狗微信对纯 HTTP 反爬，自动发现受限→如实标注）
    for url in MANUAL_ARTICLES:
        try:
            j = fetch_article(url)
            if j:
                out.append(j)
        except Exception as e:
            print("[%s] 人工清单文章失败 %s" % (CHANNEL, str(e)[:80]))
    if not MANUAL_ARTICLES:
        print("[%s] 受限：搜狗微信反爬（需浏览器），公众号文章自动发现暂不可用；"
              "内容源由政企渠道国企平台/公共招聘网间接覆盖；阶段二浏览器登录态恢复" % CHANNEL)
    return out


if __name__ == "__main__":
    jobs = fetch()
    print("公众号渠道抓取 %d 条" % len(jobs))
    for j in jobs[:10]:
        print(" -", j["职位名"][:40], "|", j["来源"])
