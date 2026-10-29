# -*- coding: utf-8 -*-
"""
求职Agent · 每日推送确定性编排（code as policy）
================================================
把每日推送提示词里的确定性环节沉淀为可复跑代码：
  候选输入 → rules.json 规则过滤(filter.JobRules) → exclusion_learned 追加排除
  → 增量去重(title+company 双键) → 生成 3 类产物。

输入（Agent 扫描结果，标准 schema，与 scan_<date>_platform/nonplatform.json 一致）：
  {
    "date": "20261023", "channel": "platform",
    "availability": {...},
    "candidates": [
      {"职位名","公司","薪资","地点","来源","作息","工作地址","链接","JD摘要","外包属性","备注","通勤","综合分","复推"}
    ]
  }
产物（输出到 job-agent 目录）：
  - to_push_<date>.json        通过+未重复的岗位，含每条判定理由（供 Agent 做时效验证/写备注）
  - records_create_<date>.json 多维表格扁平 payload：{"create_records":[{字段:值,...}]}，投递状态="未投"
  - daily_<date>.json          补推判据：date/total_scanned/after_filter/dedup_removed/...
                               /re_pushed_skip/pushed/commute_verified/jobs[]/来源构成统计

用法：
  python push_pipeline.py --date 20261023 [--candidates <file>] [--repost-limit 5]
                          [--write] [--verify] [--summary]
  --write   真正写多维表格（默认只生成 payload 文件）
  --verify  写后 record-list 回读校验
"""
import argparse, json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
RULES_PATH = os.path.join(HERE, "rules.json")
PUSHED_PATH = r"<PROJECT_ROOT>\jobs_data\pushed_jobs.json"
RECORDS_PATH = os.path.join(HERE, "all_records_raw.json")
EXCLUSION_PATH = os.path.join(HERE, "exclusion_learned.json")

# 多维表格字段（保持与表 schema 一致；写入顺序即展示顺序）
BASE_FIELDS = ["职位名", "公司", "薪资", "地点", "来源", "作息", "状态", "备注", "投递链接", "投递状态", "综合分"]

DEFAULT_DAILY_NOTE = ""  # 由 Agent 在 --note 或写表后补充，不编造


def norm(s):
    return (s or "").replace(" ", "").replace("\u3000", "").lower()


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def config():
    c = load_json(CONFIG_PATH, {})
    return c.get("feishu", {}).get("bitable", {}) or {}


# ---------------------------------------------------------------- 候选读取
def read_candidates(date, cand_file=None):
    """按 scan 命名规则或 --candidates 读候选，返回 (date, candidates)"""
    files = []
    if cand_file:
        files.append(cand_file)
    else:
        for ch in ("platform", "nonplatform"):
            p = os.path.join(HERE, "scan_%s_%s.json" % (date, ch))
            if os.path.exists(p):
                files.append(p)
    cands, meta = [], {}
    for p in files:
        d = load_json(p, {})
        if not d:
            print("!! 未找到候选文件 %s" % p)
            continue
        cands.extend(d.get("candidates", []))
        meta.setdefault("availability", {}).update(d.get("availability", {}) or {})
        meta["scan_stats"] = d.get("scan_stats", {})
    return date, cands, meta


# ---------------------------------------------------------------- 判定
def commute_tags(job):
    """从候选的 通勤/备注 提取 ✅/❌/⏳ 标签，附加进 note 供 filter 判定。"""
    note = job.get("备注") or ""
    cm = job.get("通勤") or ""
    if "❌" in (cm + note):
        return "fail"
    if "✅" in (cm + note):
        return "pass"
    # 结构化通勤分字段
    bike = job.get("通勤_骑行分") or job.get("骑行分")
    transit = job.get("通勤_公交分") or job.get("公交分")
    if isinstance(bike, (int, float)) and bike <= 30:
        return "pass"
    if isinstance(transit, (int, float)) and transit <= 60:
        return "pass"
    return "unmeasured"


def evaluate(job, rules):
    """复用 filter.JobRules 的确定性判定；返回 (判定dict, 统一字段dict)"""
    import filter as F
    jr = F.JobRules(rules)

    j = F.pick(job)  # title/company/salary/loc/source/worktime/status/apply/note/link
    # 通勤：将 Agent 实测结果合并进 note（filter 的 commute_label 从 note 读标签）
    tag = commute_tags(job)
    if tag != "unmeasured":
        j["note"] = (j["note"] or "") + ("✅通勤达标" if tag == "pass" else "❌通勤超圈")
    d = jr.evaluate(j)
    j["worktime"] = j["worktime"] or job.get("作息") or ""
    j["source"] = j["source"] or job.get("来源") or ""
    j["link"] = j["link"] or job.get("链接") or ""
    return d, j


def apply_learned(d, job, learned, rules):
    """exclusion_learned 追加排除：公司婉拒≥1 不推；类别婉拒≥2 该类排除。"""
    title = (job.get("职位名") or job.get("title") or "")
    company = (job.get("公司") or job.get("company") or "")
    if not learned:
        return d, []
    added = []
    nk = norm(company)
    for ce in learned.get("company_excluded", []):
        if norm(ce.get("company")) == nk:
            added.append("学习排除-公司婉拒过(%s×%d)" % (ce["company"][:12], ce["reject_count"]))
            break
    blob = norm(title)
    for cat in learned.get("category_excluded", []):
        if cat.get("count", 0) < 2:
            continue  # 累计婉拒不足2次，不触发整类排除（规则：同类要求累计婉拒≥2该类排除）
        hits = [k for k in cat.get("keywords", []) if k in blob]
        if hits:
            added.append("学习排除-类别婉拒≥2(%s)" % cat["category"])
            break  # 一个类别命中即排除，不叠加
    if added:
        d["pushable"] = "no"
    d["blocks"] = list(d.get("blocks", [])) + added
    return d, added


# ---------------------------------------------------------------- 增量去重
def build_known_keys():
    """已知岗位双键：pushed_jobs.json 全部 + 多维表格全量（含投递状态）。返回 (keys→status_map)"""
    known = {}
    pushed = load_json(PUSHED_PATH, []) or []
    for p in pushed:
        k = (norm(p.get("title")), norm(p.get("company")))
        known[k] = "已投"  # 进过 pushed_jobs 即视为已推（历史 push 过）
    rows = load_json(RECORDS_PATH, []) or []
    for r in rows:
        k = (norm(r.get("职位名")), norm(r.get("公司")))
        if k not in known:
            known[k] = r.get("投递状态") or "未投"
    return known


def dedup(job, known, repost_limit):
    """返回 (decision, reason)。decision ∈ new/repost/skip_repost_limit/skip_already"""
    title = norm(job.get("职位名") or job.get("title") or "")
    company = norm(job.get("公司") or job.get("company") or "")
    key = (title, company)
    hist = known.get(key)
    if hist is None:
        return "new", ""
    if hist == "未投":
        if job.get("复推"):
            return "repost", "复推（历史已推但未投，重新时效验证后推送）"
        return "skip_repost_limit", "已推且未投但未标记复推"
    return "skip_already", "已在库且投递状态=%s，不再推" % hist


def limit_repost(kind, repost_n, limit):
    """复推单日限量（main 循环用）：kind=repost 且当日已复推数超限 → 跳过。
    返回 (final_kind, new_repost_n)。"""
    if kind == "repost":
        repost_n += 1
        if repost_n > limit:
            return "skip_repost_limit", repost_n
    return kind, repost_n


# ---------------------------------------------------------------- 产物
def build_records(jobs, date):
    """多维表格扁平 payload：{"create_records":[{字段:值,...}]}，投递状态固定"未投" """
    recs = []
    for j in jobs:
        rec = {
            "职位名": (j.get("职位名") or "")[:80],
            "公司": (j.get("公司") or "")[:60],
            "薪资": (j.get("薪资") or "")[:60],
            "地点": (j.get("地点") or "")[:80],
            "来源": (j.get("来源") or "")[:20],
            "作息": (j.get("作息") or "")[:40],
            "状态": "推荐",
            "备注": (j.get("备注") or "")[:600],
            "投递链接": (j.get("链接") or j.get("投递链接") or "")[:300],
            "投递状态": "未投",
        }
        sc = j.get("综合分")
        if sc is None:
            sc = j.get("score")
        if sc is not None:
            rec["综合分"] = str(sc)
        recs.append(rec)
    return {"create_records": recs}


def build_daily(date, total_scanned, filtered, deduped, to_push, note, meta,
                pending_verify=0, closed_removed=0, commute_removed=0):
    """补推判据（格式与 daily_<date>.json 历史一致）。
    verified_open = 时效验证=在招 且 通勤实测达标 的最终推送数；
    未完成时效/通勤验证的岗位计入 pending_verify，不虚报 pushed。"""
    from collections import Counter
    verified = [j for j in to_push if (j.get("时效验证") == "在招" and j.get("commute_tag") == "pass")]
    src = Counter((j.get("来源") or "未知") for j in verified)
    platform_cnt = sum(v for k, v in src.items() if k in ("BOSS", "智联", "51job", "猎聘", "拉勾", "应届生网"))
    nonplatform_cnt = len(verified) - platform_cnt
    return {
        "date": date,
        "source": note or DEFAULT_DAILY_NOTE,
        "total_scanned": total_scanned,
        "after_filter": len(filtered),
        "dedup_removed": deduped.get("re_pushed_skip", 0) + deduped.get("skip_already", 0),
        "re_pushed_skip": deduped.get("re_pushed_skip", 0),
        "closed_removed": closed_removed,
        "commute_removed": commute_removed,
        "pending_verify": pending_verify,
        "verified_open": len(verified),
        "pushed": len(verified),
        "commute_verified": sum(1 for j in verified if j.get("commute_tag") == "pass"),
        "jobs": [
            {
                "职位名": j.get("职位名"), "公司": j.get("公司"), "薪资": j.get("薪资"),
                "地点": j.get("地点"), "来源": j.get("来源"), "作息": j.get("作息"),
                "状态": "推荐", "备注": j.get("备注"), "投递链接": j.get("链接"),
                "综合分": j.get("综合分") or "", "投递状态": "未投",
                "复推": bool(j.get("复推")),
            } for j in verified
        ],
        "source_breakdown": dict(src),
        "source_quota": {"nonplatform_min": 3, "nonplatform_actual": nonplatform_cnt},
    }


def write_bitable(records, verify=False):
    """调 lark-cli 写多维表格；--verify 时回读。返回是否成功。"""
    b = config()
    if not b.get("base_token") or not b.get("table_id"):
        print("!! config.json 缺少 base_token/table_id，跳过写表")
        return False
    payload = os.path.join(HERE, "records_create_%s.json" % RECORDS_DATE)
    save_json(payload, records)
    cmd = ["lark-cli", "base", "+record-batch-create",
           "--base-token", b["base_token"], "--table-id", b["table_id"],
           "--json", "@" + payload]
    print(">> 写多维表格: %s" % " ".join(cmd))
    r = subprocess_run(cmd)
    ok = r.returncode == 0
    print(r.stdout[-1500:] if ok else ("!! 写表失败 exit=%d\n%s" % (r.returncode, r.stderr[-800:])))
    if ok and verify:
        cmd2 = ["lark-cli", "base", "+record-list", "--base-token", b["base_token"],
                "--table-id", b["table_id"], "--page-size", "5", "--format", "json"]
        r2 = subprocess_run(cmd2)
        print("回读校验(前5条): %s" % r2.stdout[-800:] if r2.returncode == 0 else "回读失败")
    return ok


def subprocess_run(cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def engine(cands, known, rules, learned, repost_limit=5):
    """确定性核心（可注入、可单测）：候选 → 过滤/学习排除/时效/通勤/去重 → 结果。
    输入：
      cands     候选列表（scan schema，中文键）
      known     双键已知映射（build_known_keys 的产物，测试可注入 fixture）
      rules     rules.json 规则（单一事实源；测试可传真实文件内容）
      learned   exclusion_learned.json（可为 {}）
      repost_limit 复推单日上限
    返回：
      total_scanned/filtered/deduped/to_push/closed_removed/commute_removed/pending_verify
    main() 负责落盘与摘要；测试直接断言本函数输出。"""
    filtered, deduped = [], {"re_pushed_skip": 0, "skip_already": 0, "repost": 0}
    closed_removed, commute_removed, pending_verify = 0, 0, 0
    repost_n = 0
    for job in cands:
        job.setdefault("职位名", job.get("title", ""))
        job.setdefault("公司", job.get("company", ""))
        job.setdefault("来源", job.get("source", ""))
        job.setdefault("作息", job.get("worktime", ""))
        d, j = evaluate(job, rules)
        j["commute_tag"] = commute_tags(job)
        # 学习排除
        d, learned_blocks = apply_learned(d, job, learned, rules)
        # 通勤实测（第四步）：evaluate 已把 ❌ 判为硬性"通勤超圈"，这里单独计数
        if j["commute_tag"] == "fail":
            commute_removed += 1
        # 硬性不推则记录原因，不产出
        if d["pushable"] in ("no",):
            j["_block"] = "、".join(d["blocks"])
            continue
        # 时效验证（第五步）：Agent 在候选里填 时效验证=在招/已关闭/未验证
        vf = (job.get("时效验证") or "未验证").strip()
        if vf == "已关闭" or "关闭" in vf or "下线" in vf or "不存在" in vf or vf == "404":
            closed_removed += 1
            j["_block"] = "时效验证-已关闭/下线"
            continue
        # 通勤实测（第四步）：fail 直接剔除（理论上已被 evaluate 拦截，双保险）
        if j["commute_tag"] == "fail":
            commute_removed += 1
            j["_block"] = "通勤超圈(实测fail)"
            continue
        # 去重
        kind, why = dedup(job, known, repost_limit)
        kind, repost_n = limit_repost(kind, repost_n, repost_limit)
        if kind == "new":
            j["_dedup"] = "new"
        elif kind == "repost":
            j["_dedup"] = "repost"
            j["复推"] = True
            deduped["repost"] += 1
        else:
            deduped["skip_already"] += 1 if kind == "skip_already" else 0
            deduped["re_pushed_skip"] += 1 if kind == "skip_repost_limit" else 0
            j["_dedup"] = why or ("复推当日超限" if kind == "skip_repost_limit" else "已在库")
            filtered.append(j)
            continue
        # 综合分（候选显式给 or 从备注提取）
        if j.get("score") and not job.get("综合分"):
            job["综合分"] = j["score"]
        # 合并回候选字段（备注/链接以候选为准，含 Agent 二审内容）
        out = {
            "职位名": job.get("职位名") or j.get("title"),
            "公司": job.get("公司") or j.get("company"),
            "薪资": job.get("薪资") or j.get("salary"),
            "地点": job.get("地点") or j.get("loc"),
            "来源": job.get("来源") or j.get("source"),
            "作息": job.get("作息") or j.get("worktime"),
            "备注": job.get("备注") or j.get("note"),
            "链接": job.get("链接") or j.get("link"),
            "综合分": job.get("综合分"),
            "复推": bool(job.get("复推")),
            "时效验证": vf,
            "commute_tag": j["commute_tag"],
            "_dedup": j["_dedup"],
            "_blocks": d["blocks"] if d["blocks"] else "",
            "_match": d.get("match", ""),
            "_salary": d.get("salary", ""),
        }
        filtered.append(out)
        if vf == "在招" and j["commute_tag"] == "pass":
            pass  # 已验证在招且通勤达标
        else:
            pending_verify += 1

    # 最终待推送：通过过滤 + 去重新增/复推（含待验证与已验证）
    to_push = [j for j in filtered if j.get("_dedup") in ("new", "repost")]
    return {
        "total_scanned": len(cands),
        "filtered": filtered,
        "deduped": deduped,
        "to_push": to_push,
        "closed_removed": closed_removed,
        "commute_removed": commute_removed,
        "pending_verify": pending_verify,
    }


def main():
    ap = argparse.ArgumentParser(description="每日推送确定性编排")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"))
    ap.add_argument("--candidates", default=None, help="候选文件（替代 scan_<date>_*.json）")
    ap.add_argument("--repost-limit", type=int, default=5)
    ap.add_argument("--write", action="store_true", help="写多维表格（默认仅生成 payload）")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    global RECORDS_DATE
    RECORDS_DATE = args.date

    date, cands, meta = read_candidates(args.date, args.candidates)
    if not cands:
        print("!! 无候选输入，结束（date=%s）" % date)
        return

    rules = load_json(RULES_PATH, {})
    learned = load_json(EXCLUSION_PATH, {})
    known = build_known_keys()
    res = engine(cands, known, rules, learned, args.repost_limit)
    filtered, deduped = res["filtered"], res["deduped"]
    to_push, pending_verify = res["to_push"], res["pending_verify"]
    closed_removed, commute_removed = res["closed_removed"], res["commute_removed"]

    # 产物落盘
    t1 = os.path.join(HERE, "to_push_%s.json" % date)
    save_json(t1, {"date": date, "candidates": to_push})
    records = build_records(to_push, date)
    t2 = os.path.join(HERE, "records_create_%s.json" % date)
    save_json(t2, records)
    daily = build_daily(date, len(cands), filtered, deduped, to_push, "", meta,
                        pending_verify=pending_verify, closed_removed=closed_removed,
                        commute_removed=commute_removed)
    t3 = os.path.join(HERE, "daily_%s.json" % date)
    save_json(t3, daily)

    # 可选：写多维表格
    if args.write:
        write_bitable(records, verify=args.verify)

    # 摘要
    if args.summary or True:
        print("=== 每日推送编排完成 %s ===" % date)
        print("候选扫描: %d（平台+非平台合并）" % len(cands))
        print("过滤通过(含学习排除后): %d；硬性剔除(外包/角色/薪资/作息/经验/学习): %d"
              % (len(filtered), len(cands) - len(filtered) - closed_removed - commute_removed))
        print("时效验证已关闭剔除: %d；通勤实测超圈剔除: %d" % (closed_removed, commute_removed))
        print("去重: 新增 %d / 复推 %d / 跳过(已推未投超限) %d / 跳过(已投或婉拒) %d"
              % (sum(1 for j in to_push if j["_dedup"] == "new"),
                 deduped["repost"], deduped["re_pushed_skip"], deduped["skip_already"]))
        print("待推送池: %d（待时效验证/通勤实测 %d）→ to_push_%s.json"
              % (len(to_push), pending_verify, date))
        print("多维表格 payload: records_create_%s.json（投递状态=未投，%d 条）" % (date, len(records["create_records"])))
        print("补推判据: daily_%s.json（verified_open=%d pushed=%d，%s）"
              % (date, daily["verified_open"], daily["pushed"],
                 "当日推送已完成" if daily["pushed"] >= 1 else "未完成验证：仅过滤池，缺时效验证/通勤实测，补推检查会触发补跑"))
        print("来源构成: %s" % json.dumps(daily["source_breakdown"], ensure_ascii=False))
        nf = daily["source_quota"]["nonplatform_actual"]
        print("非平台配额(最终推送内): %d（下限3，%s）" % (nf, "达标" if nf >= 3 else "缺口%s" % (3 - nf)))
        if to_push:
            print("\n待推送岗位（Agent 需补 时效验证/通勤 后重跑生成最终 daily）：")
            for j in to_push[:15]:
                tag = "复推" if j["_dedup"] == "repost" else "新增"
                v = "✓在招" if j.get("时效验证") == "在招" else "待验证"
                c = ("✓通勤" if j["commute_tag"] == "pass" else ("❌" if j["commute_tag"] == "fail" else "待实测"))
                print("  [%s %s %s] %s｜%s（%s）" % (tag, v, c, j["公司"][:16], j["职位名"][:22], j["来源"]))
                if j.get("_blocks"):
                    print("        判定备注: %s" % j["_blocks"])
        else:
            print("\n!! 今日无通过岗位——请检查候选质量或规则口径（如实上报，不编造配额）")


if __name__ == "__main__":
    main()
