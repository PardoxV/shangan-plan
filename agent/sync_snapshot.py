# -*- coding: utf-8 -*-
"""把多维表格快照转成 UI 重建脚本期望的 ndjson 格式。
每次定时任务写完多维表格后：python dump_all.py && python sync_snapshot.py && python rebuild_ui.py --publish
"""
import json, io, os

if not os.path.exists("all_records_raw.json"):
    raise SystemExit("!! 缺少 all_records_raw.json，请先运行 python dump_all.py")
try:
    raw = json.load(io.open("all_records_raw.json", encoding="utf-8"))
except Exception as e:
    raise SystemExit("!! all_records_raw.json 读取失败(%s)，请重跑 python dump_all.py 后重试" % e)
out = []
for r in raw:
    # 投递状态：未投/已投/已回复/面试/婉拒/入职
    apply_state = r.get("投递状态") or ""
    # 投递反馈：待定/合适/不合适/已投
    feedback = r.get("投递反馈") or ""
    # 状态字段：推荐/优先/自查/待核/已投
    status = r.get("状态") or "待核"
    # 综合分
    try:
        score = int(float(r.get("综合分") or 0))
    except Exception:
        score = 0
    out.append({
        "title": r.get("职位名") or "",
        "company": r.get("公司") or "",
        "salary": r.get("薪资") or "",
        "loc": r.get("地点") or "",
        "source": r.get("来源") or "",
        "worktime": r.get("作息") or "未注明",
        "status": status,
        "apply": apply_state,
        "fb": feedback,
        "score": score,
        "note": r.get("备注") or "",
        "link": r.get("投递链接") or "",
        "record_id": r.get("record_id") or "",
    })

with io.open("all_jobs_snapshot.ndjson", "w", encoding="utf-8") as f:
    for j in out:
        f.write(json.dumps(j, ensure_ascii=False) + "\n")
print(f"sync done: {len(out)} rows -> all_jobs_snapshot.ndjson")
