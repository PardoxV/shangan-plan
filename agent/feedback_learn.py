# -*- coding: utf-8 -*-
"""
求职Agent · 第〇步：反馈记忆读取与学习（code as policy）
========================================================
把每日推送提示词里的「第〇步-反馈记忆读取与学习」沉淀为可复跑代码。

输入：all_records_raw.json（多维表格全量导出；可用 --dump-first 先跑 dump_all.py 拉最新）
输出：exclusion_learned.json
  {
    "generated_at": "...",
    "input_file": "all_records_raw.json",
    "status_counts": { "未投": 69, "已投": 32, ... },        # 投递状态分布
    "feedback_counts": { "待定": 95, ... },                  # 投递反馈分布
    "company_excluded": [                                   # 婉拒≥1 的公司 → 该公司岗位不再推
      {"company": "...", "reject_count": 2, "jobs": ["..."]}
    ],
    "category_excluded": [                                  # 某类要求累计婉拒≥2 → 该类直接排除
      {"category": "视频/Caption方向", "keywords": [...], "count": 6, "jobs": [...]}
    ],
    "repostable": [                                         # 投递状态=未投 且 综合分≥min_score 且非黑名单 → 可复推池（单日≤5 由推送编排限量）
      {"record_id","title","company","score","link","reason"}
    ],
    "rules": "公司婉拒≥1不推；同类要求婉拒≥2该类排除；未投好岗可复推(单日≤5)"
  }

用法：python feedback_learn.py [--dump-first] [--min-score 70]
"""
import argparse, json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDS = os.path.join(HERE, "all_records_raw.json")
RULES_PATH = os.path.join(HERE, "rules.json")

# 婉拒原因类别（从历史婉拒记录 + skill_gate 归纳；命中词条累计婉拒≥2 → 整类排除）
CATEGORIES = [
    {"name": "视频/Caption方向", "keywords": ["视频", "caption", "影视", "漫剧", "动画", "制作师"]},
    {"name": "剪辑/作品集硬技能", "keywords": ["剪辑", "作品集"]},
    {"name": "代码/技术硬技能", "keywords": ["python", "java", "代码", "开发", "算法", "后端", "前端", "工程师"]},
    {"name": "资深/经验硬要求", "keywords": ["高级", "资深", "专家", "3-5年", "5年以上"]},
]


def norm(s):
    return (s or "").replace(" ", "").replace("\u3000", "").lower()


def load_records(path=RECORDS):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rules(path=RULES_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_score(note):
    m = re.search(r"综合分(\d+)", note or "")
    return int(m.group(1)) if m else None


def build_exclusion(rows, rules, min_score):
    status_counts = {}
    feedback_counts = {}
    company_rejects = {}    # company -> {"count": n, "jobs": [...]}
    category_counts = {}    # category -> {"count": n, "jobs": [...]}
    repostable = []

    outsource = set(norm(c) for c in (rules.get("outsource_blacklist") or {}).get("companies", []))
    company_blk = set(norm(c) for c in (rules.get("company_blacklist") or {}).get("companies", []))

    for r in rows:
        status = r.get("投递状态") or ""
        feedback = r.get("投递反馈") or ""
        status_counts[status] = status_counts.get(status, 0) + 1
        feedback_counts[feedback] = feedback_counts.get(feedback, 0) + 1

        title = r.get("职位名") or ""
        company = r.get("公司") or ""
        reason = r.get("被拒原因") or ""
        note = r.get("备注") or ""
        link = r.get("投递链接") or ""

        # 1) 婉拒 → 公司级排除
        if status == "婉拒":
            ck = norm(company)
            entry = company_rejects.setdefault(ck, {"company": company, "reject_count": 0, "jobs": []})
            entry["reject_count"] += 1
            entry["jobs"].append("%s｜%s" % (title[:24], reason[:60]))

            # 2) 婉拒 → 类别级排除（职位名+拒因合并计数）
            blob = norm(title + " " + reason)
            for cat in CATEGORIES:
                hits = [k for k in cat["keywords"] if k in blob]
                if hits:
                    c = category_counts.setdefault(cat["name"], {"category": cat["name"], "keywords": cat["keywords"], "count": 0, "jobs": []})
                    c["count"] += 1
                    c["jobs"].append("%s｜%s" % (company[:16], title[:20]))

        # 3) 未投好岗 → 复推池（非外包黑名单、非公司黑名单、综合分≥阈值）
        if status == "未投":
            score = r.get("综合分")
            try:
                score = int(float(score)) if score not in (None, "") else None
            except Exception:
                score = None
            if score is None:
                score = extract_score(note)
            ck = norm(company)
            if score is not None and score >= min_score \
               and ck not in outsource and ck not in company_blk \
               and ck not in company_rejects:
                repostable.append({
                    "record_id": r.get("record_id", ""),
                    "title": title,
                    "company": company,
                    "score": score,
                    "link": link,
                    "source": r.get("来源", ""),
                    "reason": "未投好岗复推候选（综合分%d，单日≤5由推送编排限量）" % score,
                })

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_file": os.path.basename(RECORDS),
        "status_counts": status_counts,
        "feedback_counts": feedback_counts,
        "company_excluded": sorted(company_rejects.values(), key=lambda x: -x["reject_count"]),
        "category_excluded": sorted(category_counts.values(), key=lambda x: -x["count"]),
        "repostable": sorted(repostable, key=lambda x: -x["score"]),
        "rules": "公司婉拒≥1不推；同类要求婉拒≥2该类直接排除；未投好岗可复推(单日≤5)",
    }


def main():
    ap = argparse.ArgumentParser(description="第〇步：反馈记忆读取与学习")
    ap.add_argument("--dump-first", action="store_true", help="先跑 dump_all.py 拉取多维表格最新全量")
    ap.add_argument("--min-score", type=int, default=70, help="复推池综合分阈值（默认70）")
    args = ap.parse_args()

    if args.dump_first:
        r = os.system("%s %s" % (sys.executable, os.path.join(HERE, "dump_all.py")))
        if r != 0:
            print("!! dump_all.py 失败，使用现有 all_records_raw.json")

    rows = load_records()
    rules = load_rules()
    out = build_exclusion(rows, rules, args.min_score)

    dest = os.path.join(HERE, "exclusion_learned.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=== 反馈记忆学习完成 → %s ===" % dest)
    print("投递状态分布:", json.dumps(out["status_counts"], ensure_ascii=False))
    print("婉拒公司(%d):" % len(out["company_excluded"]))
    for c in out["company_excluded"]:
        print("  %s ×%d" % (c["company"], c["reject_count"]))
    print("婉拒类别(%d):" % len(out["category_excluded"]))
    for c in out["category_excluded"]:
        print("  %s ×%d %s" % (c["category"], c["count"], c["keywords"]))
    print("未投复推池(%d) 前5:" % len(out["repostable"]))
    for r in out["repostable"][:5]:
        print("  [%d分] %s｜%s" % (r["score"], r["company"][:16], r["title"][:22]))


if __name__ == "__main__":
    main()
