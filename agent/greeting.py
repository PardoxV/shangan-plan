# -*- coding: utf-8 -*-
"""
greeting.py — 可选「AI 打招呼语」生成器
=========================================
按岗位信息生成两段话：
  1) 打招呼语（≤60字）：用于 BOSS / 智联 / 51job 私信开场
  2) 简历一句话摘要（≤40字）：投递时附在备注里的个人亮点

两种模式：
  * LLM 模式（推荐）：配置 config.json 的 llm 段（DeepSeek 或任意
    OpenAI 兼容 API），按求职者画像真实生成。
  * 模板兜底模式：不配置 Key 或调用失败时，自动退回本地模板拼装，
    保证功能永远可用。

用法：
  python greeting.py --title "AI训练师" --company "某公司" --salary "10-15K" \
      --desc "文本/图片标注" [--keywords "AIGC,标注"]
  python greeting.py --file jobs.json --out greetings.json   # 批量
  python greeting.py --sample                                 # 打印示例
"""

import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None


# ---------- 配置读取 ----------

def load_config():
    """读取 agent/config.json；不存在则返回空 dict。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_profile():
    """读取 agent/profile.json；不存在则返回空 dict。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 模板兜底 ----------

def template_greeting(job, profile):
    title = job.get("title", "该岗位")
    company = job.get("company", "")
    industry = profile.get("skill_profile", {}).get("target_industry", "AI 行业")
    org = f"{company}" if company else ""
    return (
        f"您好！我是求职者，正在找{industry}方向机会，"
        f"看到贵司「{title}」与我的背景比较匹配，"
        f"希望能进一步沟通，期待您的回复。"
    )


def template_summary(job, profile):
    title = job.get("title", "")
    company = job.get("company", "")
    salary = job.get("salary", "")
    keywords = job.get("keywords", "")
    parts = [title]
    if company:
        parts.append(company)
    if salary:
        parts.append(salary)
    if keywords:
        parts.append(f"关键词：{keywords}")
    s = "｜".join(parts)
    return s[:40]


# ---------- LLM 模式 ----------

def llm_greeting(job, profile, cfg):
    """调用 OpenAI 兼容 chat API 生成；失败返回 None。"""
    if requests is None:
        return None
    llm = cfg.get("llm", {})
    api_key = llm.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    base_url = (llm.get("base_url") or "https://api.deepseek.com").rstrip("/")
    model = llm.get("model") or "deepseek-chat"
    if not api_key:
        return None

    skill = profile.get("skill_profile", {})
    strengths = "、".join(skill.get("strengths", [])[:3]) or "学习能力强"
    target = skill.get("target_industry", "AI 行业")

    system_msg = (
        "你是一名求职顾问。请基于求职者画像与岗位信息，输出严格 JSON：\n"
        "{\"greeting\":\"...\", \"summary\":\"...\"}\n"
        "要求：greeting 为给招聘方的主动打招呼语（≤60字，语气诚恳，突出匹配点，"
        "不提真实姓名，不要暴露使用 AI 生成）；summary 为简历一句话摘要（≤40字，"
        "突出求职者最相关的优势）。只输出 JSON，不要输出其他文字。"
    )
    user_msg = json.dumps({
        "求职者画像": {
            "目标行业": target,
            "主要优势": strengths,
            "备注": skill.get("coding", ""),
        },
        "岗位信息": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", ""),
            "location": job.get("location", ""),
            "desc": (job.get("desc", "") or "")[:300],
            "keywords": job.get("keywords", ""),
        },
    }, ensure_ascii=False)

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
                "max_tokens": 300,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.strip("`").strip()
        if content.startswith("json"):
            content = content[4:].strip()
        parsed = json.loads(content)
        return {
            "greeting": parsed.get("greeting", ""),
            "summary": parsed.get("summary", ""),
        }
    except Exception:
        return None


# ---------- 主流程 ----------

def generate_one(job, profile, cfg):
    job = {k: v for k, v in job.items() if v is not None}
    result = llm_greeting(job, profile, cfg)
    if result:
        return {
            "mode": "llm",
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "greeting": result["greeting"],
            "summary": result["summary"],
        }
    return {
        "mode": "template",
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "greeting": template_greeting(job, profile),
        "summary": template_summary(job, profile),
    }


def main():
    ap = argparse.ArgumentParser(description="上岸计划 · AI 打招呼语生成器")
    ap.add_argument("--title", help="岗位标题")
    ap.add_argument("--company", help="公司名称")
    ap.add_argument("--salary", help="薪资区间，如 10-15K")
    ap.add_argument("--desc", help="岗位描述片段")
    ap.add_argument("--keywords", help="关键词，逗号分隔")
    ap.add_argument("--file", help="批量：job 数组 JSON 文件")
    ap.add_argument("--out", help="批量结果输出路径（默认 greetings.json）")
    ap.add_argument("--sample", action="store_true", help="打印示例")
    args = ap.parse_args()

    cfg = load_config()
    profile = load_profile()

    if args.sample:
        demo = {
            "title": "AI训练师(文本/图片标注)",
            "company": "示例公司",
            "salary": "10-15K",
            "keywords": "AIGC,数据标注",
        }
        print(json.dumps(generate_one(demo, profile, cfg), ensure_ascii=False, indent=2))
        return

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        results = [generate_one(j, profile, cfg) for j in jobs]
        out = args.out or "greetings.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        llm_n = sum(1 for r in results if r["mode"] == "llm")
        print(f"完成 {len(results)} 条；LLM 生成 {llm_n} 条，模板兜底 {len(results) - llm_n} 条。")
        print(f"结果已写入 {out}")
        return

    job = {
        "title": args.title or "该岗位",
        "company": args.company or "",
        "salary": args.salary or "",
        "desc": args.desc or "",
        "keywords": args.keywords or "",
    }
    print(json.dumps(generate_one(job, profile, cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
