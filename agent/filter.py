# -*- coding: utf-8 -*-
"""
求职Agent · 确定性过滤引擎（code as policy）
=============================================
职责：把 rules.json 中的业务规则翻译为可审计、可复现的确定性判定。
设计原则：
  1. 规则唯一权威 = rules.json（改规则只改文件，不改本脚本）
  2. 本脚本只做"确定性判定"；语义判断（读JD判断匹配度、薪资真实性二审、
     备注撰写）留给 LLM，两者边界在 check_* 函数注释中标明
  3. 每条岗位输出结构化判定结果（decisions），可落盘、可回溯
  4. --diff 模式：对比 golden.json，做规则变更回归测试（P1）

用法：
  python filter.py --data <岗位数据文件> --out <报告路径> [--summary] [--diff <golden.json>]
  岗位数据文件支持两种格式：
    A. 多维表格导出 ndjson（字段：职位名/公司/薪资/地点/来源/作息/状态/备注/投递链接/投递状态）
    B. pushed_jobs.json（字段：title/company/salary/loc/source/.../note/link/status）
"""
import argparse
import json
import os
import re
import sys

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")


# ---------------------------------------------------------------- 加载规则
def load_rules(path=RULES_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 文本工具
def norm(s):
    return (s or "").replace(" ", "").replace("\u3000", "").lower()


def has_any(text, keywords):
    t = norm(text)
    return [k for k in keywords if k and norm(k) in t]


# ---------------------------------------------------------------- 判定器
class JobRules:
    """将 rules.json 翻译为确定性判定。每个 check_* 返回 (通过?, 说明)。"""

    def __init__(self, rules):
        self.r = rules

    # --- 1. 外包黑名单（无条件排除；同时检查公司名与备注代发）---
    def check_outsource(self, company, note=""):
        hit = has_any(company, self.r["outsource_blacklist"]["companies"])
        if hit:
            return False, "外包黑名单命中(公司名): %s" % "、".join(hit)
        hit_n = has_any(note, self.r["outsource_blacklist"]["companies"])
        if hit_n:
            return False, "外包黑名单命中(备注代发): %s" % "、".join(hit_n)
        return True, ""

    # --- 2. 岗位性质排除 ---
    def check_role(self, title):
        hit = has_any(title, self.r["exclude_roles"]["keywords"])
        if hit:
            return False, "岗位性质排除命中: %s" % "、".join(hit)
        return True, ""

    # --- 3. 匹配度分层（语义判断辅助：本函数按关键词初判，LLM可复核）---
    def match_level(self, title):
        # v5.0：先 high 再 medium 最后 skip。
        # 否则"课程开发/提示词工程师"会先被 skip 的"开发/工程师"误杀。
        if has_any(title, self.r["match_levels"]["high"]["roles"]):
            return "high"
        if has_any(title, self.r["match_levels"]["medium"]["roles"]):
            return "medium"
        if has_any(title, self.r["match_levels"]["skip"]["roles"]):
            return "skip"
        return "other"

    # --- 4. 薪资审核（确定性规则；LLM可在此基础上做市场价二审）---
    @staticmethod
    def _parse_salary(s):
        """把 '4-5K' / '6000-8000元/月' / '7.3-8.8K' / '10-15K·14薪' 解析为 (lo, hi) 元。
        支持小数薪资（如 7.3K=7300）。"""
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
        if not nums:
            return None
        # 出现 K / k 后缀或"千"字说明单位是千
        if re.search(r"\d\s*[kK]", s) or "千" in s:
            nums = [n * 1000 for n in nums]
        lo, hi = int(min(nums)), int(max(nums))
        if lo == 0:
            return None
        return lo, hi

    def check_salary(self, salary_text, title=""):
        r = self.r["salary"]
        s = norm(salary_text)
        if not s:
            return "unknown", "薪资未注明"
        parsed = self._parse_salary(s)
        if parsed is None:
            if has_any(s, r["suspect_rules"]["text_suspect"]):
                return "suspect", "面议/薪资未明确"
            return "unknown", "薪资文本无可解析数字"
        lo, hi = parsed
        # 高于 15K：仅高匹配方向（AI视频/AIGC/内容创作）可推；标注/审核类 15K+ 跳过
        if hi > r["max_push"]:
            if has_any(title, r["suspect_rules"]["skip_15k_roles"]):
                return "reject", "标注/审核类 %dK 超 15K，跳过" % (hi // 1000)
            if has_any(title, r["suspect_rules"]["high_match_15k"]):
                return "pass", "高匹配方向 %dK，超 15K 但可争取" % (hi // 1000)
            return "reject", "薪资上限 %dK 超 15K 且非高匹配方向" % (hi // 1000)
        # 2) 上限都低于 5K → 拒绝
        if hi < r["preferred_range"][0]:
            return "reject", "薪资上限 %dK 低于 5K 下限" % (hi // 1000)
        # 3) 区间比 > 1.5 → 存疑降级
        if hi > lo and (hi / lo) > r["suspect_rules"]["ratio_suspect"]:
            return "suspect", "薪资区间比 %.1f 倍 > 1.5，标'薪资存疑'降级" % (hi / lo)
        # 4) v5.0 税前下限分档（卡下限/到手，修复旧版只卡上限的缺陷）
        pts = r.get("pre_tax_screen", {})
        if pts:
            lp_lo = pts.get("likely_pass_lo", 6500)
            cb_lo = pts.get("confirm_band_lo", 5000)
            if lo >= lp_lo:
                return "pass", "税前下限 %gK≥%gK，大概率到手≥5000" % (lo / 1000, lp_lo / 1000)
            if lo >= cb_lo:
                return "confirm", "税前下限 %gK 在%g-%gK，投递前必须确认到手≥5000" % (lo / 1000, cb_lo / 1000, lp_lo / 1000)
            return "lowsal", "税前下限 %gK<%gK，到手大概率不足，不主推" % (lo / 1000, cb_lo / 1000)
        return "pass", "薪资区间 %d-%dK 在可推范围" % (lo // 1000, hi // 1000)

    # --- 5. 作息检查（关键词初判；LLM 读 JD 二审）---
    def check_schedule(self, worktime_text):
        r = self.r["work_schedule"]
        if not worktime_text:
            return "unknown", "作息未注明"
        # 夜班/轮休/安全值班等
        block_kws = list(r["exclude"]) + r.get("night_rotation_block_keywords", [])
        if has_any(worktime_text, block_kws):
            return "reject", "作息排除命中: %s" % "、".join(has_any(worktime_text, block_kws))
        # 周末零休（周末两天都上班、周中休）
        wz = r.get("weekend_zero_rest_keywords", [])
        if wz and has_any(worktime_text, wz) and \
           not has_any(worktime_text, ["双休", "周末休", "周末单休"]):
            return "reject", "周末零休命中: %s" % "、".join(has_any(worktime_text, wz))
        if has_any(worktime_text, r["accept"]):
            return "pass", "作息符合: %s" % "、".join(has_any(worktime_text, r["accept"]))
        return "unknown", "作息需人工确认: %s" % worktime_text

    # --- 5b. 经验硬门槛（v5.0：消费 skill_gate.experience_hard_block）---
    def check_experience(self, *texts):
        r = self.r["skill_gate"].get("experience_hard_block", {})
        text = " ".join(t or "" for t in texts)
        if not text:
            return True, ""
        hits = has_any(text, r.get("block_keywords", []))
        if not hits:
            return True, ""
        if has_any(text, r.get("override_pass_keywords", [])):
            return True, "经验要求但命中应届/无经验豁免"
        return False, "经验硬门槛命中: %s" % "、".join(hits)

    # --- 6. 通勤判定（从已实测备注提取；未实测时返回 unknown 要求高德实测）---
    def commute_label(self, note):
        n = note or ""
        if "❌" in n:
            return "fail"
        if "✅" in n:
            return "pass"
        if "⚠️" in n:
            return "warn"
        if "⏳" in n:
            return "unknown"
        return "unmeasured"

    # --- 汇总：一条岗位的完整判定 ---
    def evaluate(self, job):
        title = job.get("title") or job.get("职位名") or ""
        company = job.get("company") or job.get("公司") or ""
        salary = job.get("salary") or job.get("薪资") or ""
        worktime = job.get("worktime") or job.get("作息") or ""
        note = job.get("note") or job.get("备注") or ""
        status = job.get("status") or job.get("状态") or ""
        jd = job.get("jd") or job.get("JD") or job.get("经验要求") or ""

        d = {}
        d["outsource_ok"], d["outsource_note"] = self.check_outsource(company, note)
        d["role_ok"], d["role_note"] = self.check_role(title)
        d["match"] = self.match_level(title)
        d["salary"], d["salary_note"] = self.check_salary(salary, title)
        d["schedule"], d["schedule_note"] = self.check_schedule(worktime)
        d["exp_ok"], d["exp_note"] = self.check_experience(title, jd, note)
        d["commute"] = self.commute_label(note)

        # 可推送性综合判定
        blocks = []
        if not d["outsource_ok"]:
            blocks.append("外包黑名单")
        if not d["role_ok"]:
            blocks.append("岗位性质排除")
        if not d["exp_ok"]:
            blocks.append("经验硬门槛")
        if d["salary"] == "reject":
            blocks.append("薪资不达标")
        elif d["salary"] == "suspect":
            blocks.append("薪资存疑(降级)")
        elif d["salary"] == "confirm":
            blocks.append("待确认到手(降级)")
        elif d["salary"] == "lowsal":
            blocks.append("薪资下限不足(降级)")
        if d["schedule"] == "reject":
            blocks.append("作息排除")
        if d["match"] == "skip":
            blocks.append("匹配度过低(不推)")
        if d["commute"] == "fail":
            blocks.append("通勤超圈")
        if d["commute"] == "unmeasured":
            blocks.append("通勤未实测")

        HARD = {"外包黑名单", "岗位性质排除", "经验硬门槛", "薪资不达标",
                "作息排除", "匹配度过低(不推)", "通勤超圈"}
        SOFT = {"薪资存疑(降级)", "待确认到手(降级)", "薪资下限不足(降级)"}
        if not blocks:
            d["pushable"] = "yes"
        elif any(b in HARD for b in blocks):
            d["pushable"] = "no"
        elif "通勤未实测" in blocks:
            d["pushable"] = "needs_measure"
        elif any(b in SOFT for b in blocks):
            d["pushable"] = "downgrade"
        else:
            d["pushable"] = "no"

        d["blocks"] = blocks
        return d


# ---------------------------------------------------------------- 数据读取
def load_jobs(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ndjson":
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if "record_id" in r:
                    rows.append(r)
        return rows
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("jobs", [])


def pick(job):
    """统一字段名，便于下游使用。"""
    def g(*names, default=""):
        for n in names:
            if job.get(n):
                v = job[n]
                if isinstance(v, list):
                    v = v[0] if v else ""
                return v
        return default
    return {
        "record_id": job.get("record_id", ""),
        "title": g("title", "职位名"),
        "company": g("company", "公司"),
        "salary": g("salary", "薪资"),
        "loc": g("loc", "地点"),
        "source": g("source", "来源"),
        "worktime": g("worktime", "作息"),
        "status": g("status", "状态"),
        "apply": g("apply", "投递状态", default="未投"),
        "note": g("note", "备注"),
        "link": g("link", "投递链接"),
    }


# ---------------------------------------------------------------- 回归测试（P1）
def run_diff(golden_path, results):
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)
    base = {}
    for g in golden.get("items", []):
        base[(g["title"], g["company"])] = g["golden"]

    changes = []
    counts = {"不变": 0, "变严": 0, "变宽": 0}
    order = {"yes": 0, "downgrade": 1, "needs_measure": 2, "no": 3}
    for r in results:
        j, d = r["job"], r["decision"]
        key = (j["title"], j["company"])
        old = base.get(key)
        if old is None:
            continue
        new_push = d["pushable"]
        if old["pushable"] == new_push:
            counts["不变"] += 1
            continue
        # 变严 = 从更宽松变为更严格
        if order.get(old["pushable"], 9) < order.get(new_push, 9):
            counts["变严"] += 1
        else:
            counts["变宽"] += 1
        changes.append({
            "title": j["title"], "company": j["company"],
            "old": old["pushable"], "new": new_push,
            "old_blocks": old["blocks"], "new_blocks": d["blocks"],
        })

    print("-" * 56)
    print("回归测试（对比 %s）" % os.path.basename(golden_path))
    print("  判定变化: 不变 %d | 变严 %d | 变宽 %d" % (counts["不变"], counts["变严"], counts["变宽"]))
    if changes:
        print("  变更清单（前15条）:")
        for c in changes[:15]:
            print("    [%s -> %s] %s | %s" % (c["old"], c["new"], c["title"][:20], c["company"][:12]))
            print("      旧阻塞:%s" % c["old_blocks"])
            print("      新阻塞:%s" % c["new_blocks"])
    else:
        print("  ✅ 与 golden 完全一致，规则变更未影响任何历史判定")
    return counts


def run_selftest(engine, path):
    """规则回归自测：读取标准样例，逐条比对期望（pushable 允许集合 / 必命中 / 禁命中 block）。"""
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    passed = 0
    failed = []
    for c in cases:
        d = engine.evaluate(c["input"])
        problems = []
        if "allow_pushable" in c and d["pushable"] not in c["allow_pushable"]:
            problems.append("pushable=%s 不在允许集合 %s" % (d["pushable"], c["allow_pushable"]))
        for b in c.get("must_block", []):
            if b not in d["blocks"]:
                problems.append("缺少必命中block「%s」，实际blocks=%s" % (b, d["blocks"]))
        for b in c.get("forbid_block", []):
            if b in d["blocks"]:
                problems.append("误命中block「%s」" % b)
        if problems:
            failed.append({"name": c["name"], "problems": problems})
        else:
            passed += 1
    print("=" * 56)
    print("规则回归自测: 通过 %d / 共 %d" % (passed, len(cases)))
    for x in failed:
        print("  [FAIL] %s" % x["name"])
        for p in x["problems"]:
            print("        %s" % p)
    print("=" * 56)
    return not failed


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="求职Agent确定性过滤引擎")
    ap.add_argument("--data", required=False, default="", help="岗位数据文件（ndjson 或 pushed_jobs.json）")
    ap.add_argument("--out", default="", help="报告输出路径（缺省=数据文件同目录 filter_report.json）")
    ap.add_argument("--summary", action="store_true", help="仅输出汇总统计")
    ap.add_argument("--diff", default="", help="对比 golden.json，输出规则变更影响清单（回归测试）")
    ap.add_argument("--selftest", action="store_true", help="运行规则回归自测（见 --selftest-data）")
    ap.add_argument("--selftest-data", default="rule_regression_cases.json", help="回归样例文件")
    args = ap.parse_args()

    rules = load_rules()
    engine = JobRules(rules)

    if args.selftest:
        ok = run_selftest(engine, args.selftest_data)
        sys.exit(0 if ok else 1)

    if not args.data:
        print("!! 缺少 --data；或使用 --selftest 运行回归自测")
        sys.exit(2)

    jobs = [pick(j) for j in load_jobs(args.data)]
    if not jobs:
        print("!! 未读取到岗位数据: %s" % args.data)
        sys.exit(1)

    results = []
    for j in jobs:
        d = engine.evaluate(j)
        results.append({"job": j, "decision": d})

    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(args.data)), "filter_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"rules_version": rules.get("version"), "total": len(results),
                   "results": results}, f, ensure_ascii=False, indent=1)

    # 汇总
    from collections import Counter
    push = Counter(r["decision"]["pushable"] for r in results)
    match = Counter(r["decision"]["match"] for r in results)
    salary = Counter(r["decision"]["salary"] for r in results)
    commute = Counter(r["decision"]["commute"] for r in results)
    block = Counter(b for r in results for b in r["decision"]["blocks"])

    print("=" * 56)
    print("规则版本: %s | 岗位总数: %d" % (rules.get("version"), len(results)))
    print("-" * 56)
    print("可推送性: %s" % dict(push))
    print("匹配度  : %s" % dict(match))
    print("薪资判定: %s" % dict(salary))
    print("通勤判定: %s" % dict(commute))
    print("排除原因: %s" % dict(block))
    print("-" * 56)
    print("报告已写入: %s" % out_path)

    if args.diff:
        run_diff(args.diff, results)

    if args.summary:
        return
    # 明细（前 8 条）
    for r in results[:8]:
        d = r["decision"]
        print("[%s] %s | %s" % (d["pushable"][:4], r["job"]["title"][:18], r["job"]["company"][:14]))
        for k in ("outsource_note", "role_note", "salary_note", "schedule_note", "match"):
            if d.get(k):
                print("     %s" % d[k])


if __name__ == "__main__":
    main()
