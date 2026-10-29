# -*- coding: utf-8 -*-
"""
渠道：政企官网（阶段一·公开渠道）
===============================
来源站点：
  1. 成都人事考试网（cdpta.cdrsigc.com）——事业单位/公务员/社会化选聘公告
  2. 蓉漂人才网（cdrchr.cn）——增量政策性岗位/国企招考公告
  3. 成都人才网职位搜索（job.rc114.com）——最新招聘职位
  4. 双流人才网（slrc114.cn）——双流区本地企业招聘（用户所在地）
  5. 成都公共招聘网（cd.sc91.org.cn）——人社系统公共招聘

每个站点解析为统一 schema 岗位条目；站点不可用时抛异常由 run_all 记录受限原因。
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

CHANNEL = "政企"

# ---------------------------------------------------------------- 站点1：成都人事考试网
def fetch_cdpta():
    jobs = []
    url = "https://cdpta.cdrsigc.com/netpage/index.do"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    for title, href in links:
        t = common.clean_title(title)
        if not t:
            continue
        # 只保留招聘/招考/选聘/招募类公告；过滤导航与系统链接
        if not any(k in t for k in ("招聘", "招考", "选聘", "招募", "引进", "考录", "遴选", "聘用", "招录")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "考试计划", "政策法规", "办事指南", "关于我们", "常见问题", "资料下载", "考点地图")):
            continue
        jobs.append({
            "职位名": t[:60],
            "公司": "成都市人事考试中心/相关招考单位",
            "薪资": "按公告（政企岗位，需看公告正文）",
            "地点": "成都市",
            "来源": "政企-成都人事考试网",
            "作息": "未注明（机关事业单位常规双休待确认）",
            "工作地址": "成都市区（见公告）",
            "链接": href,
            "JD摘要": "政企公开招考公告，详见公告正文（报名条件/岗位表/时间节点）。",
            "外包属性": "政企正式招考（编制内或正式聘用，视公告）",
            "备注": "抓取自成都人事考试网首页公告列表；岗位明细在公告附件，投递前需读正文确认",
        })
    return jobs


# ---------------------------------------------------------------- 站点2：蓉漂人才网
def fetch_cdrchr():
    jobs = []
    # 人事招考列表页（含增量政策性岗位、国企招聘公告）
    url = "https://www.cdrchr.cn/pta/index"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    seen = set()
    for title, href in links:
        t = common.clean_title(title)
        if not t or href in seen:
            continue
        if not any(k in t for k in ("招聘", "招考", "招募", "选聘", "引进", "遴选", "招聘公告", "招聘简章")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "招聘会", "人事招考", "人才培训", "蓉漂系列", "单位中心", "联系我们")):
            continue
        seen.add(href)
        # 日期从标题尾部抓（形如 "标题\n 2026-10-26 12:"）
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
        pub = date_m.group(1) if date_m else ""
        t = re.sub(r"\s*\d{4}-\d{2}-\d{2}.*$", "", t).strip()
        jobs.append({
            "职位名": t[:60],
            "公司": "蓉漂人才网招考单位（详见公告）",
            "薪资": "按公告（政策性岗位常为5万/年包干，需读正文）",
            "地点": "成都市（各区县，见公告）",
            "来源": "政企-蓉漂人才网",
            "作息": "未注明（机关/国企常规双休待确认）",
            "工作地址": "成都市区县（见公告）",
            "链接": href,
            "JD摘要": "政企/国企/政策性岗位招考公告。发布于%s。" % (pub or "近期"),
            "外包属性": "政企正式/直签（非外包）",
            "备注": "抓取自蓉漂人才网人事招考列表；发布日期=%s；报名条件与岗位表需进公告正文核对" % (pub or "待确认"),
        })
    return jobs


# ---------------------------------------------------------------- 站点3：成都人才网职位搜索
def fetch_rc114():
    jobs = []
    url = "https://job.rc114.com/JobSearchCate.aspx"
    html = common.http_get(url, retries=1)
    # 职位条目出现在搜索结果区块；解析 a 链接与标题
    links = common.extract_links(html, url)
    # rc114 职位详情形如 JobDetail/xxxxx；公司条目和职位标题混杂，按常见模式过滤
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 4:
            continue
        if any(k in t for k in ("登录", "注册", "首页", "联系我们", "全部服务", "我的求职", "毕业生存档", "在线学习", "党费", "教育培训", "人事代理")):
            continue
        if "JobDetail" not in href and "jobdetail" not in href.lower() and "position" not in href.lower():
            continue
        jobs.append({
            "职位名": t[:60],
            "公司": "成都人才网入驻企业（详见详情页）",
            "薪资": "未注明（详见详情页）",
            "地点": "成都市",
            "来源": "政企-成都人才网",
            "作息": "未注明",
            "工作地址": "见详情页",
            "链接": href,
            "JD摘要": "成都人才网最新招聘职位，详见职位详情页。",
            "外包属性": "",
            "备注": "抓取自成都人才网职位搜索页；公司名/薪资/要求需进详情页确认",
        })
    # 若上面的详情链接过滤过严（不同页面结构），退化为"招聘会"公告兜底
    if len(jobs) < 3:
        jobs2 = []
        for title, href in common.extract_links("https://rc114.com/fair/index.aspx", "https://rc114.com/fair/index.aspx"):
            t = common.clean_title(title)
            if t and ("招聘会" in t or "专场" in t) and "index" not in href.lower():
                jobs2.append({
                    "职位名": t[:60], "公司": "成都人才网现场招聘会", "薪资": "按展位现场",
                    "地点": "成都市人才服务中心（青羊区宁夏街136号）", "来源": "政企-成都人才网",
                    "作息": "未注明", "工作地址": "成都市青羊区宁夏街136号",
                    "链接": href, "JD摘要": "现场招聘会公告，参会单位与岗位以现场为准。",
                    "外包属性": "", "备注": "抓取自成都人才网现场招聘会列表；具体岗位以现场展位为准",
                })
        jobs = jobs + jobs2
    return jobs


# ---------------------------------------------------------------- 站点4：双流人才网
def fetch_slrc():
    jobs = []
    url = "https://slrc114.cn/about/company"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 4:
            continue
        if any(k in t for k in ("首页", "登录", "注册", "关于我们", "联系我们")):
            continue
        if any(k in t for k in ("招聘", "招募", "公告", "简章")):
            jobs.append({
                "职位名": t[:60],
                "公司": "双流人才网发布单位（详见公告）",
                "薪资": "按公告",
                "地点": "成都市双流区",
                "来源": "政企-双流人才网",
                "作息": "未注明",
                "工作地址": "双流区（见公告）",
                "链接": href,
                "JD摘要": "双流区企业招聘/政策性岗位公告。",
                "外包属性": "",
                "备注": "抓取自双流人才网（用户所在地，通勤友好度由下游高德实测）",
            })
    return jobs


# ---------------------------------------------------------------- 站点5：成都公共招聘网
def fetch_sc91():
    jobs = []
    url = "https://cd.sc91.org.cn"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 4:
            continue
        if not any(k in t for k in ("招聘", "招募", "后勤", "兼职", "公益岗位")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "关于")):
            continue
        jobs.append({
            "职位名": t[:60],
            "公司": "成都公共招聘网发布单位",
            "薪资": "按原文（常注明时薪/月薪）",
            "地点": "成都市",
            "来源": "政企-成都公共招聘网",
            "作息": "未注明",
            "工作地址": "见原文",
            "链接": href,
            "JD摘要": "人社系统公共招聘信息，详见原文。",
            "外包属性": "",
            "备注": "抓取自成都公共招聘网首页；后勤/兼职/公益岗位较多，下游按规则过滤",
        })
    return jobs


# ---------------------------------------------------------------- 站点6：成都国企人才综合服务平台
def fetch_gq():
    """成都人才发展集团运营的国企招聘聚合（市属国企招聘公告，含报名时间）。"""
    jobs = []
    url = "https://gq.cdrchr.cn"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    seen = set()
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 8:
            continue
        if not any(k in t for k in ("招聘", "招募", "选聘", "笔试", "面试", "拟聘")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "联系我们", "关于", "服务指南")):
            continue
        if href in seen:
            continue
        seen.add(href)
        jobs.append({
            "职位名": t[:70],
            "公司": "成都市属国企（详见公告）",
            "薪资": "按国企薪酬体系（公告常未展开）",
            "地点": "成都市",
            "来源": "政企-成都国企人才平台",
            "作息": "未注明（国企常规双休待确认）",
            "工作地址": "见公告",
            "链接": href,
            "JD摘要": "成都市属国企公开招聘公告（报名/笔试/面试进展）。",
            "外包属性": "国企直签（以公告为准）",
            "备注": "抓取自成都国企人才综合服务平台；成都交投/交子金控/环境集团等市属国企为主，投递前读公告确认",
        })
    return jobs


# ---------------------------------------------------------------- 站点7：成都市人民政府员工招聘页
def fetch_chengdu_gov():
    """成都市政府官网员工招聘页（市属国企招聘汇总）。"""
    jobs = []
    url = "https://www.chengdu.gov.cn/cdsrmzf/c178938/cmdzfwzq_zp.shtml"
    html = common.http_get(url, retries=1)
    links = common.extract_links(html, url)
    seen = set()
    for title, href in links:
        t = common.clean_title(title)
        if not t or len(t) < 8:
            continue
        if not any(k in t for k in ("招聘", "选聘", "招募", "笔试", "面试")):
            continue
        if any(k in t for k in ("首页", "登录", "注册", "员工招聘", "市属国有企业", "德眉资")):
            continue
        if href in seen:
            continue
        seen.add(href)
        jobs.append({
            "职位名": t[:70],
            "公司": "成都市属国企（详见公告）",
            "薪资": "按公告",
            "地点": "成都市",
            "来源": "政企-成都市政府员工招聘页",
            "作息": "未注明",
            "工作地址": "见公告",
            "链接": href,
            "JD摘要": "成都市政府官网汇总的市属国企招聘公告。",
            "外包属性": "国企直签（以公告为准）",
            "备注": "抓取自成都市人民政府官网员工招聘栏目；国企招聘汇总，投递前读公告",
        })
    return jobs


def fetch():
    """合并政企子站点；单个失败不影响其他。"""
    out = []
    for fn in (fetch_cdpta, fetch_cdrchr, fetch_rc114, fetch_slrc, fetch_sc91,
               fetch_gq, fetch_chengdu_gov):
        try:
            out.extend(fn())
        except Exception as e:
            print("[%s] 子站点 %s 受限: %s" % (CHANNEL, fn.__name__, str(e)[:120]))
    return out


if __name__ == "__main__":
    jobs = fetch()
    print("政企渠道抓取 %d 条" % len(jobs))
    for j in jobs[:10]:
        print(" -", j["职位名"], "|", j["公司"][:20], "|", j["来源"])
