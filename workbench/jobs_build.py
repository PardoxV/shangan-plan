# -*- coding: utf-8 -*-
"""
上岸计划 · 岗位数据 -> UI 内嵌 JOBS 的共享构建模块（单一实现，杜绝双份拷贝）
=====================================================================
build_workbench.py 与 rebuild_ui.py 原本各自复制一份 build_js 逻辑，
改一处忘另一处即数据分叉。现统一收口到这里：

  from jobs_build import build_js, inject_js, count_jobs

职责：快照 ndjson -> "var JOBS=[...]" 字符串；把该字符串注入任意 index.html。
纯函数、无副作用、可单测（test_build.py 覆盖）。
"""
import json
import io
import re

APPLIED_STATES = {"已投", "已回复", "面试", "婉拒", "入职"}
BAD_LINK_RE = re.compile(r"(sou\.zhaopin\.com/\?|jobs\.51job\.com/all/|liepin\.com/zhaopin|\?kw=|/search\?)")
COMMUTE_RE = re.compile(r"骑行\s*(\d+)\s*分")


def extract_url(link):
    """从 '岗位名(https://...)' 或纯 URL 文本中抽出链接；拿不到返回空串。"""
    m = re.search(r"\((https?://[^)]+)\)", link or "")
    if m:
        return m.group(1)
    m2 = re.search(r"https?://\S+", link or "")
    return m2.group(0).rstrip(".,;)") if m2 else ""


def extract_note(note):
    """取推荐理由：评分拆解「综合分N（…）」之后的内容；无则取｜最后一段；再退整条前30字"""
    m = re.search(r"综合分\d+（[^）]*）([^｜]*)", note or "")
    if m and m.group(1).strip():
        return m.group(1).strip()[:30]
    parts = [p.strip() for p in note.split("｜") if p.strip()]
    return (parts[-1] if parts else note)[:30]


def commute_minutes(j):
    """通勤分钟：优先地点字段里的「骑行N分」，回退到备注。"""
    cm = _first_int(COMMUTE_RE, j.get("loc") or "")
    if cm == 0:
        cm = _first_int(COMMUTE_RE, j.get("note") or "")
    return cm


def _first_int(regex, text):
    m = regex.search(text)
    return int(m.group(1)) if m else 0


def clean_loc(j):
    """地点清洗：括号里的骑行分拆出展示、去掉行内骑行标记。"""
    loc = (j.get("loc") or "").replace("(骑行", " · 骑行").replace(")", "").replace("（", "(").replace("）", ")")
    return re.sub(r"骑行\d+分✅?", "", loc).strip(" ·")


def build_js(snap_path):
    """ndjson 快照 -> 'var JOBS=[...]' 字符串（每行一个岗位对象字面量）。"""
    rows = []
    for line in io.open(snap_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        title = (j.get("title") or "").replace("（", "(").replace("）", ")")
        note = j.get("note") or ""
        apply_state = (j.get("apply") or "").strip()
        link = extract_url(j.get("link"))
        if BAD_LINK_RE.search(link) and "链接非详情页" not in note:
            note = (note + " ⚠️链接非详情页，请在平台搜公司名+岗位名").strip()
        rows.append('{t:"%s",c:"%s",s:"%s",l:"%s",src:"%s",wt:"%s",st:"%s",ap:%d,ps:"%s",fb:"%s",sc:%d,cm:%d,note:"%s",u:"%s",r:"%s"}' % (
            title.replace('"', "'"), (j.get("company") or "").replace('"', "'"),
            (j.get("salary") or "").replace('"', "'"), clean_loc(j).replace('"', "'"),
            j.get("source", ""), j.get("worktime") or "未注明",
            j.get("status") or "待核", 1 if apply_state in APPLIED_STATES else 0,
            apply_state.replace('"', "'") or "未投",
            (j.get("fb") or "").replace('"', "'"),
            int(j.get("score") or 0), commute_minutes(j),
            extract_note(note).replace('"', "'"),
            link, (j.get("record_id") or "")))
    return "var JOBS=[\n" + ",\n".join(rows) + "\n];"


def inject_js(html, js):
    """把 build_js 产物替换进 HTML 的 var JOBS=[...]; 找不到原数组返回原 html。"""
    return re.sub(r"var\s+JOBS\s*=\s*\[[\s\S]*?\n\];", js, html, count=1)


def count_jobs(js):
    """统计 JOBS 数组里的岗位对象个数（按 '{t:"' 出现次数）。"""
    return len(re.findall(r"\{t:\"", js))


def build_from_snapshot(snap_path, index_path, label="UI数据"):
    """一步到位：快照 -> 注入 HTML -> 写盘。返回 (写入条数, 是否发生变化)。"""
    js = build_js(snap_path)
    html = io.open(index_path, encoding="utf-8").read()
    new_html = inject_js(html, js)
    if new_html == html:
        if "var JOBS=[" in html:
            return count_jobs(js), False  # 幂等：已是快照最新
        raise RuntimeError("未找到 JOBS 数组，跳过写入: %s" % index_path)
    io.open(index_path, "w", encoding="utf-8", newline="\n").write(new_html)
    return count_jobs(js), True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python jobs_build.py <snap.ndjson> <index.html> [--label 标签]")
        sys.exit(1)
    label = sys.argv[4] if len(sys.argv) > 4 else "UI数据"
    n, changed = build_from_snapshot(sys.argv[1], sys.argv[2])
    print("%s已重建%s: %d 条" % (label, "（无变化）" if not changed else "", n))
