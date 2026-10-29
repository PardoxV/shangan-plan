# -*- coding: utf-8 -*-
"""上岸计划 · 本地工作台服务
启动: python server.py  (默认端口 8123)
功能:
  1. 静态服务 job-workbench 目录下的 index.html（岗位库工作台）
  2. POST /api/mark   {record_id, title, company} -> 调 lark-cli 写多维表格「投递状态=已投」
  3. GET  /api/rules  -> 返回权威 rules.json 摘要 + 当前 override 规则
  4. POST /api/rules  -> 保存 override 规则到 workbench_rules.json（不修改权威 rules.json）
"""
import json, os, re, secrets, subprocess, sys, datetime, urllib.parse
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("WORKBENCH_PORT", "8123"))

# 本地写操作令牌（防本机其他进程/外部页面伪造请求改多维表格）
# 首次启动自动生成到 workbench_token.txt；前端从 GET /api/token 读取（同源可读，跨源被 CORS 拦截）
TOKEN_FILE = HERE / "workbench_token.txt"
TOKEN_HEADER = "X-Workbench-Token"

def load_token():
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(tok) >= 16:
            return tok
    tok = secrets.token_hex(16)
    TOKEN_FILE.write_text(tok + "\n", encoding="utf-8", newline="\n")
    return tok

BASE_TOKEN = "YOUR_BASE_TOKEN"
TABLE_ID = "YOUR_TABLE_ID"
BASE_URL = "https://my.feishu.cn/base/YOUR_BASE_TOKEN"

# 权威规则文件（只读）与 override 规则文件（工作台可调）
AUTH_RULES = HERE.parent / "job-agent" / "rules.json"
OVERRIDE_FILE = HERE / "workbench_rules.json"

# 简历文件（本地工作台内嵌打开：GET /resume 返回 PDF）
RESUME_FILE = Path(r"<USER_DESKTOP>\求职者的简历.pdf")

DEFAULT_OVERRIDE = {
    "bike_max_min": 30,
    "transit_max_min": 60,
    "salary_min_take_home": 5000,
    "salary_max_push": 15000,
    "weekend_rest_min_days": 1,
    "block_outsource": False,   # 2026-10-14用户口径：外包放开硬排除，仅作背景参考
    "block_company_blacklist": False,
    "enabled": True,
    # 2026-10-29 全字段可编辑扩展（工作台可改，保存到 override，不影响权威推送）
    "directions": [],                 # [{name, priority}]
    "commute_must_measure_with": "",  # 实测方式说明
    "salary_pre_tax_rule": "",        # 税前判定说明
    "work_schedule_exclude": [],      # 作息排除关键词
    "exclude_roles_keywords": [],     # 排除角色关键词
    "outsource_companies": [],        # 外包公司库
    "company_blacklist_companies": [],# 公司黑名单
    "skill_gate_user_lacks": [],      # 用户不具备技能
    "skill_gate_block_keywords": [],  # 硬性不推关键词
    "skill_gate_override_pass_keywords": [],  # 豁免词
}

def load_override():
    if OVERRIDE_FILE.exists():
        try:
            data = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_OVERRIDE)
            merged.update(data or {})
            return merged
        except Exception:
            pass
    return dict(DEFAULT_OVERRIDE)

def save_override(data):
    merged = dict(DEFAULT_OVERRIDE)
    if isinstance(data, dict):
        merged.update(data)
    OVERRIDE_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                             encoding="utf-8", newline="\n")
    return merged

def rules_summary():
    """从权威 rules.json 提取关键规则摘要（只读权威文件）"""
    summary = {}
    if AUTH_RULES.exists():
        try:
            auth = json.loads(AUTH_RULES.read_text(encoding="utf-8"))
            summary["version"] = auth.get("version", "?")
            summary["updated_at"] = auth.get("updated_at", "")
            commute = auth.get("commute", {})
            summary["commute"] = {
                "bike_max_min": next((c.get("max_min") for c in commute.get("pass_any_of", [])
                                      if c.get("mode") == "bike"), None),
                "transit_max_min": next((c.get("max_min") for c in commute.get("pass_any_of", [])
                                         if c.get("mode") == "public_transit_incl_walk"), None),
                "must_measure_with": commute.get("must_measure_with", ""),
            }
            sal = auth.get("salary", {})
            hard = sal.get("hard_line", {})
            summary["salary"] = {
                "metric": hard.get("metric", ""),
                "min_take_home": hard.get("min_take_home"),
                "max_push": sal.get("max_push"),
                "rule": sal.get("pre_tax_screen", {}).get("rule", ""),
            }
            ws = auth.get("work_schedule", {})
            summary["work_schedule"] = {
                "weekend_rest_min_days": ws.get("require", {}).get("weekend_rest_min_days"),
                "no_rotation": ws.get("require", {}).get("no_rotation"),
                "legal_holidays_off": ws.get("require", {}).get("legal_holidays_off"),
                "exclude": ws.get("exclude", []),
            }
            summary["exclude_roles_count"] = len(auth.get("exclude_roles", {}).get("keywords", []))
            summary["outsource_count"] = len(auth.get("outsource_blacklist", {}).get("companies", []))
            summary["company_blacklist_count"] = len(auth.get("company_blacklist", {}).get("companies", []))
            summary["outsource_companies"] = auth.get("outsource_blacklist", {}).get("companies", [])
            summary["company_blacklist_companies"] = auth.get("company_blacklist", {}).get("companies", [])
            summary["exclude_roles_keywords"] = auth.get("exclude_roles", {}).get("keywords", [])
            summary["skill_gate"] = {
                "user_lacks": auth.get("skill_gate", {}).get("user_lacks", []),
                "block_keywords_count": len(auth.get("skill_gate", {}).get("block_keywords", [])),
                "block_keywords": auth.get("skill_gate", {}).get("block_keywords", []),
                "override_pass_keywords": auth.get("skill_gate", {}).get("override_pass_keywords", []),
            }
            summary["target"] = auth.get("user_profile", {}).get("target", "")
            summary["directions"] = [{"name": d.get("name"), "priority": d.get("priority")}
                                     for d in auth.get("directions", {}).get("lines", [])]
            summary["learned_exclusion"] = [{"pattern": r.get("pattern"), "reject_count": r.get("reject_count")}
                                            for r in auth.get("feedback_loop", {}).get("learned_exclusion", {}).get("rules", [])]
        except Exception as e:
            summary["error"] = str(e)
    else:
        summary["error"] = "权威 rules.json 不存在"
    return summary

def build_template():
    """把个人定制规则抽象为可分享的通用规则模板（去隐私、可参数化、带注释）"""
    summary = rules_summary()
    ov = load_override()
    tpl = {
        "name": "上岸计划·求职筛选规则模板",
        "format_version": 1,
        "created": datetime.date.today().isoformat(),
        "description": "由『上岸计划』工作台导出的通用求职筛选规则。导入后可按自己的城市/通勤/薪资/作息修改参数，"
                       "不需要会写规则引擎。",
        "commute": {
            "bike_max_min": ov.get("bike_max_min", 30),
            "transit_max_min": ov.get("transit_max_min", 60),
            "note": "通勤上限（分钟）：骑行 OR 公交地铁任一达标即可；需用高德门址实测，禁止按片区估算。",
        },
        "salary": {
            "min_take_home": ov.get("salary_min_take_home", 5000),
            "max_push": ov.get("salary_max_push", 15000),
            "note": "月到手薪资底线 / 推送上限（元）。",
        },
        "work_schedule": {
            "weekend_rest_min_days": ov.get("weekend_rest_min_days", 1),
            "no_rotation": ov.get("no_rotation", True),
            "legal_holidays_off": ov.get("legal_holidays_off", True),
            "note": "作息硬要求：每周至少休 N 天、不接受轮班、法定节假日休。",
        },
        "exclude_roles": ov.get("exclude_roles_keywords") or summary.get("exclude_roles_keywords", []),
        "skill_gate": {
            "user_lacks": ov.get("skill_gate_user_lacks") or summary.get("skill_gate", {}).get("user_lacks", []),
            "block_keywords_count": len(ov.get("skill_gate_block_keywords")
                                        or summary.get("skill_gate", {}).get("block_keywords", [])),
            "override_pass_keywords": ov.get("skill_gate_override_pass_keywords") or summary.get("skill_gate", {}).get("override_pass_keywords", []),
            "note": "求职者不具备的硬技能 + 硬性不推关键词 + 豁免词（命中豁免词可放行）。",
        },
        "blacklists": {
            "outsource_companies": ov.get("outsource_companies") or summary.get("outsource_companies", []),
            "company_blacklist": ov.get("company_blacklist_companies") or summary.get("company_blacklist_companies", []),
            "note": "外包公司与公司黑名单（导入后可按需开启拦截开关）。",
        },
        "directions": ov.get("directions") or summary.get("directions", []),
        "learned_exclusion": summary.get("learned_exclusion", []),
        "override": ov,
    }
    return tpl

# 字段名（与多维表格一致）
F_APPLY = "投递状态"      # select: 未投/已投/已回复/面试/婉拒/入职
F_APP_DATE = "投递日期"   # datetime
F_FEEDBACK = "投递反馈"   # select: 待定/合适/不合适/已投

APPLY_STATES = {"未投", "已投", "已回复", "面试", "婉拒", "入职"}
FEEDBACK_STATES = {"待定", "合适", "不合适", "已投"}

def run_lark(args, timeout=60):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out

def find_record_by_title(title, company):
    """在快照 ndjson 里按 title+company 找 record_id（兜底：前端若没传 rid）"""
    snap = HERE.parent / "job-agent" / "all_jobs_snapshot.ndjson"
    if not snap.exists():
        return ""
    for line in snap.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        if (j.get("title") == title) and (j.get("company") == company):
            return j.get("record_id") or ""
    return ""

def update_state(record_id, state, feedback=None):
    """写多维表格：投递状态=state、（可选）投递反馈=feedback、若转为已投则补投递日期。写后回读验证。"""
    payload = {"update_records": {record_id: {}}}
    fields = payload["update_records"][record_id]
    fields[F_APPLY] = [state]
    if feedback:
        fields[F_FEEDBACK] = [feedback]
    if state == "已投":
        fields[F_APP_DATE] = datetime.date.today().strftime("%Y-%m-%d") + " 00:00:00"
    tmp = HERE / "_status_payload.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    try:
        rc, out = run_lark([
            "lark-cli", "base", "+record-batch-update",
            "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
            "--json", "@" + str(tmp), "--as", "user",
        ])
        if rc != 0:
            return False, ("lark-cli 返回非零: " + out[:300])
        rc2, out2 = run_lark([
            "lark-cli", "base", "+record-get",
            "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
            "--record-id", record_id, "--as", "user",
        ])
        verified = False
        if rc2 == 0:
            m = re.search(r'"record_file":\s*"([^"]+)"', out2)
            if m:
                rf = m.group(1).replace("\\\\", "\\")
                try:
                    with open(rf, encoding="utf-8") as f:
                        rec = json.load(f)
                    verified = (rec.get(F_APPLY) == [state]) or (rec.get(F_APPLY) == state)
                except Exception:
                    verified = False
            if not verified and state in out2:
                verified = True
        if verified:
            return True, "ok"
        return False, ("写后回读未确认: " + out2[:300])
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

def mark_applied(record_id):
    """写多维表格：投递状态=已投、投递日期=今天、投递反馈=已投。返回 (ok, msg)"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    payload = {
        "update_records": {
            record_id: {
                F_APPLY: ["已投"],
                F_APP_DATE: today + " 00:00:00",
                F_FEEDBACK: ["已投"],
            }
        }
    }
    tmp = HERE / "_mark_payload.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    try:
        rc, out = run_lark([
            "lark-cli", "base", "+record-batch-update",
            "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
            "--json", "@" + str(tmp), "--as", "user",
        ])
        if rc != 0:
            return False, ("lark-cli 返回非零: " + out[:300])
        # 回读验证：解析 +record-get 返回的 record ndjson 文件，检查「投递状态」字段
        rc2, out2 = run_lark([
            "lark-cli", "base", "+record-get",
            "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
            "--record-id", record_id, "--as", "user",
        ])
        verified = False
        if rc2 == 0:
            m = re.search(r'"record_file":\s*"([^"]+)"', out2)
            if m:
                rf = m.group(1).replace("\\\\", "\\")
                try:
                    with open(rf, encoding="utf-8") as f:
                        rec = json.load(f)
                    verified = (rec.get(F_APPLY) == ["已投"]) or (rec.get(F_APPLY) == "已投")
                except Exception as e:
                    verified = False
            if not verified and ("\u5df2\u6295" in out2 or "已投" in out2):
                verified = True
        if verified:
            return True, "ok"
        return False, ("写后回读未确认: " + out2[:300])
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

class Handler(SimpleHTTPRequestHandler):
    server_version = "ShangAnWorkbench/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_token(self):
        """写操作鉴权：请求头必须携带本机令牌。返回 None 表示通过，否则返回 401 响应。"""
        tok = self.headers.get(TOKEN_HEADER, "")
        if tok and secrets.compare_digest(tok, load_token()):
            return None
        self._send_json({"ok": False, "error": "unauthorized: 缺少或错误的 X-Workbench-Token"}, 401)
        return self

    def do_OPTIONS(self):
        # 同源场景无需 CORS；不再返回任何跨域头，外部页面无法跨域读写本服务
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        denied = self._require_token()
        if denied:
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/mark":
            self._handle_mark()
            return
        if parsed.path == "/api/status":
            self._handle_status()
            return
        if parsed.path == "/api/rules/import":
            self._handle_rules_import()
            return
        if parsed.path == "/api/rules":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except Exception as e:
                self._send_json({"ok": False, "error": "bad json: %s" % e}, 400)
                return
            saved = save_override(data)
            self._send_json({"ok": True, "saved": saved, "summary": rules_summary()})
            return
        self._send_json({"ok": False, "error": "not found"}, 404)

    def _handle_rules_import(self):
        """导入规则模板：接受 {template:{...}} 或 {override:{...}}，合并进 override 落盘"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except Exception as e:
            self._send_json({"ok": False, "error": "bad json: %s" % e}, 400)
            return
        tpl = data.get("template")
        if not tpl:
            tpl = {"override": data.get("override") or {}}
        src = tpl.get("override") if isinstance(tpl, dict) else {}
        if not isinstance(src, dict):
            self._send_json({"ok": False, "error": "模板缺少 override 字段"}, 400)
            return
        # 只吸收模板中合法的 override 键（避免注入未知键）
        allowed = set(DEFAULT_OVERRIDE.keys())
        picked = {k: v for k, v in src.items() if k in allowed and v is not None}
        saved = save_override(picked)
        self._send_json({"ok": True, "imported": list(picked.keys()),
                         "saved": saved, "summary": rules_summary()})

    def _handle_mark(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send_json({"ok": False, "error": "bad json: %s" % e}, 400)
            return
        record_id = (data.get("record_id") or "").strip()
        title = (data.get("title") or "").strip()
        company = (data.get("company") or "").strip()
        if not record_id:
            record_id = find_record_by_title(title, company)
        if not record_id:
            self._send_json({"ok": False, "error": "缺少 record_id 且快照中未找到该岗位"}, 400)
            return
        ok, msg = mark_applied(record_id)
        self._send_json({"ok": ok, "msg": msg, "record_id": record_id,
                         "base_url": BASE_URL})

    def _handle_status(self):
        """更新投递状态/反馈：{record_id, state, feedback?}。状态值白名单校验。"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send_json({"ok": False, "error": "bad json: %s" % e}, 400)
            return
        record_id = (data.get("record_id") or "").strip()
        state = (data.get("state") or "").strip()
        feedback = (data.get("feedback") or "").strip() or None
        if not record_id:
            record_id = find_record_by_title((data.get("title") or "").strip(),
                                             (data.get("company") or "").strip())
        if not record_id:
            self._send_json({"ok": False, "error": "缺少 record_id 且快照中未找到该岗位"}, 400)
            return
        if state not in APPLY_STATES:
            self._send_json({"ok": False, "error": "非法投递状态: %s（合法值: %s）"
                             % (state, "/".join(sorted(APPLY_STATES)))}, 400)
            return
        if feedback and feedback not in FEEDBACK_STATES:
            self._send_json({"ok": False, "error": "非法投递反馈: %s（合法值: %s）"
                             % (feedback, "/".join(sorted(FEEDBACK_STATES)))}, 400)
            return
        ok, msg = update_state(record_id, state, feedback)
        self._send_json({"ok": ok, "msg": msg, "record_id": record_id,
                         "state": state, "base_url": BASE_URL})

    def _send_pdf(self, path):
        """返回 PDF 文件流（浏览器内嵌打开）"""
        if not path or not path.exists():
            self._send_json({"ok": False, "error": "简历文件不存在"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", 'inline; filename="resume.pdf"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/resume":
            self._send_pdf(RESUME_FILE)
            return
        if parsed.path == "/api/token":
            self._send_json({"ok": True, "token": load_token()})
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "ts": datetime.datetime.now().isoformat()})
            return
        if parsed.path == "/api/rules/export":
            self._send_json({"ok": True, "template": build_template()})
            return
        if parsed.path == "/api/rules":
            self._send_json({"ok": True, "override": load_override(), "summary": rules_summary()})
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        sys.stderr.write("[workbench] %s\n" % (fmt % args))

if __name__ == "__main__":
    print("上岸计划 · 本地工作台  http://localhost:%d" % PORT)
    print("投递按钮 -> 直接写飞书多维表格（投递状态=已投）")
    print("多维表格: %s" % BASE_URL)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
