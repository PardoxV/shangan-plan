# -*- coding: utf-8 -*-
"""
job-scraper · 通用模块
=======================
统一 schema、HTTP 抓取、正文解析、清洗、落盘、与上游（push_pipeline/filter）对接。

岗位统一 schema（与 job-agent/filter.py 的 pick() + push_pipeline scan 格式兼容）：
    {
      "职位名": str,        # 必填
      "公司":   str,        # 必填
      "薪资":   str,        # 可空（如 "面议(需确认)"）
      "地点":   str,        # 可空
      "来源":   str,        # 渠道标识，如 "政企-成都人事考试网" / "高校-电子科大就业网" / "公众号-成都人才招聘网"
      "作息":   str,        # 可空（如 "未注明" / "双休"）
      "工作地址": str,      # 可空（尽量精确，供高德通勤实测）
      "链接":   str,        # 岗位原文/详情 URL（可空，时效验证用）
      "JD摘要": str,        # 岗位描述/要求摘要
      "外包属性": str,      # 可空（"国企直签" / "外包" / ""）
      "备注":   str,        # 抓取时的补充说明（不含人工二审内容）
      "通勤":   "",         # 抓取阶段恒为空，由下游高德实测填充
      "综合分": None,       # 抓取阶段不评分，由下游评分
      "复推":   False,      # 抓取阶段恒 False
      "抓取时间": "YYYY-MM-DD HH:MM:SS"
    }
"""
import hashlib, json, os, re, sys, time, datetime, ssl, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw_jobs")
LOG_DIR = os.path.join(HERE, "logs")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

REQUIRED_FIELDS = ["职位名", "公司", "来源"]


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_tag():
    return datetime.date.today().strftime("%Y%m%d")


# ---------------------------------------------------------------- HTTP
def http_get(url, timeout=25, headers=None, retries=1, encoding="utf-8", ssl_ok=False):
    """GET 文本；失败抛异常。retries 为额外重试次数。
    ssl_ok=True 时不校验证书（部分政企/国企官网证书链不完整）。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,*/*",
        **(headers or {})})
    ctx = None
    if ssl_ok:
        ctx = ssl._create_unverified_context()
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read()
                # 按响应头或指定编码解码；失败降级 utf-8
                try:
                    return body.decode(encoding)
                except Exception:
                    for enc in ("utf-8", "gbk", "gb2312", "utf-16"):
                        try:
                            return body.decode(enc)
                        except Exception:
                            continue
                    return body.decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(1.2 * (i + 1))
    raise last


def http_get_bytes(url, timeout=25, headers=None, retries=1):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", **(headers or {})})
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(1.2 * (i + 1))
    raise last


# ---------------------------------------------------------------- 解析工具
def strip_html(html):
    """去除 HTML 标签与多余空白，保留基本文本。"""
    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|td)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def extract_links(html, base_url=""):
    """提取 (text, href) 列表，href 归一为绝对地址。"""
    out = []
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html):
        href, txt = m.group(1).strip(), strip_html(m.group(2))[:80]
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        if base_url and not href.startswith("http"):
            href = urllib.parse.urljoin(base_url, href)
        out.append((txt, href))
    return out


def first_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def clean_title(t):
    t = (t or "").strip()
    t = re.sub(r"[\s\u3000]+", " ", t)
    t = re.sub(r"[【\[]\s*[0-9]+\s*[】\]]\s*", "", t)  # 【12】编号前缀
    return t[:120]


# ---------------------------------------------------------------- 落盘
def save_raw(channel, jobs, date=None):
    """写 raw_jobs/<channel>_<date>.ndjson（一行一条 JSON）。返回文件路径。"""
    if not os.path.isdir(RAW_DIR):
        os.makedirs(RAW_DIR, exist_ok=True)
    date = date or today_tag()
    path = os.path.join(RAW_DIR, "%s_%s.ndjson" % (channel, date))
    lines = []
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for j in jobs:
            lines.append(json.dumps(j, ensure_ascii=False))
        f.write("\n".join(lines))
    return path


def load_raw(channel, date=None):
    path = os.path.join(RAW_DIR, "%s_%s.ndjson" % (channel, date or today_tag()))
    jobs = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    jobs.append(json.loads(line))
                except Exception:
                    continue
    return jobs


def validate_jobs(jobs, channel):
    """返回 (合法列表, 丢弃数, 丢弃原因样例)"""
    ok, drop, why = [], 0, {}
    for j in jobs:
        miss = [f for f in REQUIRED_FIELDS if not (j.get(f) or "").strip()]
        if miss:
            drop += 1
            why["缺字段:%s" % ",".join(miss)] = why.get("缺字段:%s" % ",".join(miss), 0) + 1
            continue
        j.setdefault("来源", channel)
        j.setdefault("薪资", "")
        j.setdefault("地点", "")
        j.setdefault("作息", "未注明")
        j.setdefault("工作地址", "")
        j.setdefault("链接", "")
        j.setdefault("JD摘要", "")
        j.setdefault("外包属性", "")
        j.setdefault("备注", "")
        j.setdefault("通勤", "")
        j.setdefault("综合分", None)
        j.setdefault("复推", False)
        j.setdefault("抓取时间", now_str())
        ok.append(j)
    return ok, drop, why


def build_scan_file(jobs, date=None, channel="aggregate", availability=None, stats=None):
    """把合并后的岗位包装成 push_pipeline.read_candidates 可读的 scan 文件。
    返回 (path, scan_dict)。"""
    date = date or today_tag()
    scan = {
        "date": date,
        "channel": channel,
        "availability": availability or {},
        "candidates": jobs,
        "scan_stats": stats or {},
    }
    path = os.path.join(HERE, "scan_auto_%s.json" % date)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scan, f, ensure_ascii=False, indent=1)
    return path, scan


# ---------------------------------------------------------------- 双键去重（抓取侧）
def norm(s):
    return re.sub(r"[\s\u3000]+", "", (s or "")).lower()


def dedup_key(job):
    return (norm(job.get("职位名")), norm(job.get("公司")))


def dedup_jobs(jobs):
    """同轮抓取内按 职位名+公司 双键去重，保留后出现者。返回 (列表, 丢弃数)"""
    seen, out, drop = set(), [], 0
    for j in jobs:
        k = dedup_key(j)
        if k in seen:
            drop += 1
            continue
        seen.add(k)
        out.append(j)
    return out, drop


# ---------------------------------------------------------------- 渠道注册
def get_channel(name):
    import importlib
    try:
        mod = importlib.import_module("channels.%s" % name)
        return mod
    except Exception as e:
        return None


def run_all(channel_names=None, limit=None, dry=False):
    """依次运行各渠道抓取，合并后落盘统一 scan 文件。
    channel_names: 指定渠道名列表（channels/ 下模块名）；None=全部注册渠道。
    limit: 每渠道最多保留岗位数（None 不限）。
    dry: True 时不写 scan 合并文件（单渠道自测用）。
    返回 {channel: {ok, count, error}}"""
    import glob
    results = {}
    all_jobs = []
    if channel_names is None:
        channel_names = [os.path.basename(p)[:-3] for p in glob.glob(os.path.join("channels", "*.py"))
                         if not os.path.basename(p).startswith("_")]
    for name in channel_names:
        mod = get_channel(name)
        if mod is None:
            results[name] = {"ok": False, "count": 0, "error": "模块加载失败"}
            continue
        try:
            jobs = mod.fetch() if hasattr(mod, "fetch") else []
            jobs, drop, why = validate_jobs(jobs, name)
            if limit:
                jobs = jobs[:limit]
            jobs, dd = dedup_jobs(jobs)
            path = save_raw(name, jobs)
            results[name] = {"ok": True, "count": len(jobs), "drop": drop,
                             "raw": path, "dedup_drop": dd,
                             "drop_why": why}
            all_jobs.extend(jobs)
        except Exception as e:
            results[name] = {"ok": False, "count": 0, "error": str(e)[:300]}
    if not dry:
        all_jobs, dd2 = dedup_jobs(all_jobs)
        scan_path, scan = build_scan_file(all_jobs, channel="aggregate_auto")
        results["_aggregate"] = {"ok": True, "count": len(all_jobs), "scan": scan_path}
        results["_dedup_drop"] = dd2
    return results


if __name__ == "__main__":
    r = run_all()
    for k, v in r.items():
        print("%s: %s" % (k, json.dumps(v, ensure_ascii=False)[:200]))
