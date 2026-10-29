# -*- coding: utf-8 -*-
"""
job-scraper · 详情页深度解析模块（B 方案核心）
=============================================
对候选列表逐条 fetch 详情页正文，提取：
  1. 工作门址（供高德通勤实测）  2. 报名截止时间（时效判定）
  3. 资格条件（学历/届别）       4. 附件型公告识别（岗位表在附件）
  5. JS 渲染/不可解析如实标记

输入：scan 候选文件（push_pipeline.read_candidates 格式，带 链接 字段）
输出：detail_enriched_<date>.json
      {date, enriched:[{...原候选字段, 工作地址(解析后), 报名截止, 学历要求,
        届别要求, 解析状态, 解析备注, 附件链接, 时效判定}], stats:{...}}

用法：python detail_parser.py [scan文件] [输出文件]
"""
import json, os, re, sys, io, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")
TODAY = datetime.date.today()

# 允许失败的域名前缀清单（已知不稳定站点，不因单个站点失败拖垮整批）
SKIP_ON_ERROR_PREFIX = ("https://mp.weixin.qq.com", "http://cdxdfy.scssfw.gov.cn")

# ---------------------------------------------------------------- 地址提取
_ADDR_PATTERNS = [
    # 显式字段
    r"工作(?:地址|地点)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9·\-（）()]{4,40})",
    r"单位(?:地址|地点)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9·\-（）()]{4,40})",
    r"办公(?:地址|地点)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9·\-（）()]{4,40})",
    r"工作场所\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9·\-（）()]{4,40})",
    r"(?:单位|公司|办公)?地址\s*[:：]\s*([\u4e00-\u9fa5A-Za-z0-9·\-（）()]{4,40})",
    # 兜底：城区名+路/街/道/巷+门牌，避开"某某区某某局"
    r"([\u4e00-\u9fa5]{2,6}(?:区|县|市)[\u4e00-\u9fa5]{1,20}(?:路|街|道|巷|大道|大街)\d{0,4}号?)",
]
# 命中后需剔除的行政单位误抓（如 "成都市人力资源和社会保障局"）
_ADDR_BAD = ("人力", "社保", "教育局", "委员会", "办公室", "管理局", "人才", "服务中心",
             "招聘", "报名", "咨询", "监督", "监察", "考试", "人民政府")


def extract_address(text):
    for pat in _ADDR_PATTERNS:
        for m in re.finditer(pat, text):
            s = re.sub(r"\s+", "", m.group(0) if len(m.groups()) == 0 else m.group(1))
            s = s.strip("，。；、,;:：")
            if len(s) < 4 or len(s) > 60:
                continue
            if ("区" not in s and "县" not in s and "市" not in s):
                continue
            if ("路" not in s and "街" not in s and "道" not in s and "巷" not in s):
                continue
            if any(b in s for b in _ADDR_BAD):
                continue
            return s
    return ""


# ---------------------------------------------------------------- 时间提取
def _to_date(s):
    """把 '2026年7月21日' / '2026-07-21' / '7月21日' 归一到 date，失败返回 None"""
    s = re.sub(r"\s+", "", s)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", s)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})月(\d{1,2})日", s)
    if m:
        return datetime.date(TODAY.year, int(m.group(1)), int(m.group(2)))
    return None


def extract_deadline(text):
    """返回 (截止date, 原文片段)。优先找 '至/截止 … 日期' 的端点。"""
    # 模式1：报名时间：2026年X月X日9:00至2026年X月X日17:00
    m = re.search(r"报名(?:时间|日期)?\s*[:：]?\s*([^。；\n]{5,80})", text)
    if m:
        seg = re.sub(r"\s+", "", m.group(1))
        ends = re.findall(r"\d{4}年?\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}月\d{1,2}日", seg)
        if ends:
            d = _to_date(ends[-1])
            if d:
                return d, seg[:60]
    # 模式2：报名截止时间：X
    m = re.search(r"(?:报名)?截止(?:时间)?\s*[:：]?\s*([^。；\n]{4,40})", text)
    if m:
        seg = re.sub(r"\s+", "", m.group(1))
        ends = re.findall(r"\d{4}年?\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}月\d{1,2}日", seg)
        if ends:
            d = _to_date(ends[-1])
            if d:
                return d, seg[:60]
    # 模式3：…至2026年X月X日截止/止
    m = re.search(r"至\s*(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*(?:17:00|24:00|截止|止)?", text)
    if m:
        d = _to_date(m.group(1))
        if d:
            return d, m.group(0)[:60]
    return None, ""


def extract_qualifications(text):
    out = {}
    m = re.search(r"(博士|硕士|研究生|本科|大专|专科)", text)
    if m:
        out["学历要求"] = m.group(1)
    m = re.search(r"20(?:2[3-9]|3[0-9])届", text)
    if m:
        out["届别要求"] = m.group(0)
    elif "应届毕业生" in text:
        out["届别要求"] = "应届毕业生"
    m = re.search(r"(\d{2})周岁", text)
    if m:
        out["年龄要求"] = m.group(1) + "周岁"
    return out


# ---------------------------------------------------------------- 附件识别
_ATTACH_EXT = ("doc", "docx", "xls", "xlsx", "pdf", "rar", "zip")


def extract_attachment(html, base_url):
    """返回附件链接列表；正文明确'岗位表见附件'时给出标注。"""
    links = []
    for txt, href in common.extract_links(html, base_url):
        if any(href.lower().endswith("." + e) for e in _ATTACH_EXT):
            links.append({"text": txt[:50], "url": href})
    return links


# ---------------------------------------------------------------- JS 渲染判定
def is_js_rendered(text):
    """正文过短且无招聘语义 → 判定为 JS 渲染/空页"""
    if len(text) < 200:
        return True
    hits = sum(1 for k in ("招聘", "岗位", "报名", "应聘", "工作", "条件") if k in text)
    return hits < 2


# ---------------------------------------------------------------- 主流程
def parse_detail(job):
    """对单条候选执行详情页解析。返回 (job副本, 解析备注, 状态, 附件链接)。"""
    url = (job.get("链接") or "").strip()
    note = []
    status = "ok"
    attach = []
    if not url:
        return job, "无链接，无法解析", "nolink", attach

    try:
        html = common.http_get(url, retries=1, timeout=20, ssl_ok=True)
    except Exception as e:
        # 已知不稳定站点不重试；其余重试一次
        try:
            html = common.http_get(url, retries=2, timeout=25, ssl_ok=True)
        except Exception as e2:
            return job, "详情页抓取失败: %s" % str(e2)[:80], "fetch_error", attach

    text = common.strip_html(html)
    if is_js_rendered(text):
        return job, "正文过短/JS渲染，无岗位内容可解析", "js_rendered", attach

    # 附件型公告：正文提附件或页面有附件链接
    attach = extract_attachment(html, url)
    if attach:
        note.append("附件%d个（岗位表可能在其中）" % len(attach))
    if "附件" in text[:2000] and any(k in text[:2000] for k in ("岗位表", "招聘计划", "职位表", "岗位信息")):
        status = "attachment"
        note.append("岗位明细在附件")

    # 地址
    addr = extract_address(text)
    if addr:
        job["工作地址"] = addr
        note.append("门址已提取: " + addr)
    else:
        note.append("正文无门址")

    # 截止
    dl, seg = extract_deadline(text)
    if dl:
        job["报名截止"] = dl.isoformat()
        if dl < TODAY:
            job["时效判定"] = "已截止"
            note.append("报名已于%s截止" % dl.isoformat())
        else:
            job["时效判定"] = "在招"
            note.append("报名截止%s" % dl.isoformat())
    else:
        job["时效判定"] = "待核"
        note.append("未提取到报名截止")

    # 资格
    qual = extract_qualifications(text)
    for k, v in qual.items():
        job[k] = v
        note.append("%s=%s" % (k, v))

    return job, "；".join(note), status, attach


def enrich(scan_path, out_path=None):
    with io.open(scan_path, encoding="utf-8") as f:
        scan = json.load(f)
    cands = scan.get("candidates", [])
    out = scan.get("candidates", [])
    stats = {"total": len(cands), "addr_ok": 0, "deadline_ok": 0,
             "expired": 0, "js_rendered": 0, "fetch_error": 0,
             "attachment": 0, "attachment_links": []}
    enriched = []
    for j in cands:
        e = dict(j)
        e["解析状态"] = "ok"
        e["解析备注"] = ""
        e["附件链接"] = []
        e["时效判定"] = "待核"
        e2, note, status, attach = parse_detail(e)
        e2["解析状态"] = status
        e2["解析备注"] = note
        e2["附件链接"] = [a["url"] for a in attach]
        if e2.get("工作地址") and "见公告" not in e2["工作地址"] and len(e2["工作地址"]) > 4:
            stats["addr_ok"] += 1
        if e2.get("报名截止"):
            stats["deadline_ok"] += 1
        if e2.get("时效判定") == "已截止":
            stats["expired"] += 1
        if status == "js_rendered":
            stats["js_rendered"] += 1
        if status == "fetch_error":
            stats["fetch_error"] += 1
        if status == "attachment":
            stats["attachment"] += 1
        if e2.get("附件链接"):
            stats["attachment_links"].extend([{"职位": e2.get("职位名", "")[:20], "url": u} for u in e2["附件链接"]][:3])
        enriched.append(e2)

    out_path = out_path or os.path.join(HERE, "detail_enriched_%s.json" % common.today_tag())
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump({"date": scan.get("date"), "stats": stats, "enriched": enriched},
                  f, ensure_ascii=False, indent=1)
    return out_path, stats, enriched


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "scan_auto_%s.json" % common.today_tag())
    out_path, stats, enriched = enrich(src)
    print("解析完成: %s" % out_path)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    for e in enriched:
        print("%s | %s | 状态=%s | 地址=%s | 截止=%s | 时效=%s" % (
            (e.get("职位名") or "")[:22], (e.get("公司") or "")[:12],
            e["解析状态"], (e.get("工作地址") or "")[:26], e.get("报名截止", ""),
            e.get("时效判定", "")))
