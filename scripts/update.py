#!/usr/bin/env python3
"""Fetch recent arXiv papers, ask Codex to rank them, and update site data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATOM = "http://www.w3.org/2005/Atom"
ARXIV_ID = re.compile(r"(?:abs/)?([^v]+?)(?:v\d+)?$")


def load_json(path: pathlib.Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def fetch_category(category: str, limit: int, retries: int = 2) -> list[dict]:
    query = urllib.parse.urlencode({
        "search_query": f"cat:{category}", "start": 0, "max_results": limit,
        "sortBy": "submittedDate", "sortOrder": "descending",
    })
    url = f"https://export.arxiv.org/api/query?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "paper-daily/1.0 (personal research feed)"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                root = ET.fromstring(response.read())
            break
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5)
    papers = []
    for entry in root.findall(f"{{{ATOM}}}entry"):
        raw_id = entry.findtext(f"{{{ATOM}}}id", "")
        match = ARXIV_ID.search(raw_id)
        paper_id = match.group(1) if match else raw_id.rsplit("/", 1)[-1]
        papers.append({
            "id": paper_id,
            "title": clean(entry.findtext(f"{{{ATOM}}}title", "")),
            "abstract": clean(entry.findtext(f"{{{ATOM}}}summary", "")),
            "authors": [clean(a.findtext(f"{{{ATOM}}}name", "")) for a in entry.findall(f"{{{ATOM}}}author")],
            "published": entry.findtext(f"{{{ATOM}}}published", "")[:10],
            "updated": entry.findtext(f"{{{ATOM}}}updated", "")[:10],
            "categories": [c.attrib.get("term", "") for c in entry.findall(f"{{{ATOM}}}category")],
            "abs_url": f"https://arxiv.org/abs/{paper_id}",
            "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        })
    return papers


def clean(value: str) -> str:
    return " ".join(value.split())


def keyword_score(paper: dict, interests: list[str]) -> int:
    text = f"{paper['title']} {paper['abstract']}".lower()
    words = {w for phrase in interests for w in re.findall(r"[a-z0-9-]{3,}", phrase.lower())}
    hits = sum(2 if word in paper["title"].lower() else 1 for word in words if word in text)
    return min(10, max(1, 3 + hits // 2))


def fallback_rank(papers: list[dict], config: dict) -> list[dict]:
    ranked = []
    for paper in papers:
        score = keyword_score(paper, config["interests"])
        ranked.append({"id": paper["id"], "score": score, "topic": "Pending Codex review",
                       "tldr_zh": paper["abstract"][:180] + ("…" if len(paper["abstract"]) > 180 else ""),
                       "reason_zh": "Initially selected from interest keywords in the title and abstract."})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def codex_rank(papers: list[dict], config: dict, model: str | None) -> list[dict]:
    payload = [{k: p[k] for k in ("id", "title", "abstract", "categories", "published")} for p in papers]
    prompt = f"""You are my research-paper editor. Score every candidate by semantic relevance to my interests, not merely by keyword overlap.
Interests: {json.dumps(config['interests'], ensure_ascii=False)}
Negative interests: {json.dumps(config.get('negative_interests', []), ensure_ascii=False)}
Output language: {config.get('language', 'en')}

Requirements:
1. Assign a score from 0 to 10. Prioritize methodological novelty, direct relevance, and work likely to influence research decisions.
2. Use a short topic label. Write tldr_zh as a one-sentence method summary and reason_zh as a concise explanation of why I should read it. Despite the legacy field names, write both values in the configured output language.
3. Return every input ID exactly once. Never invent a paper or modify an ID.

Candidate papers:
{json.dumps(payload, ensure_ascii=False)}
"""
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "ranking.json"
        cmd = ["codex", "exec", "--ephemeral", "--sandbox", "read-only",
               "--output-schema", str(ROOT / "schemas/ranking.schema.json"),
               "--output-last-message", str(output), "-"]
        if model:
            cmd[2:2] = ["--model", model]
        subprocess.run(cmd, input=prompt, text=True, check=True, timeout=900, cwd=ROOT)
        result = json.loads(output.read_text(encoding="utf-8"))["papers"]
    if {r["id"] for r in result} != {p["id"] for p in papers}:
        raise ValueError("Codex response did not contain every candidate ID exactly once")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-codex", action="store_true", help="Use deterministic keyword fallback")
    parser.add_argument("--model", default=os.getenv("CODEX_MODEL"))
    parser.add_argument("--input", type=pathlib.Path, help="Use a local arXiv-format JSON fixture")
    args = parser.parse_args()
    config = load_json(ROOT / "config.json", {})
    existing = load_json(ROOT / "site/data/papers.json", {"papers": []})
    if args.input:
        candidates = load_json(args.input, [])
    else:
        candidates = []
        for index, category in enumerate(config["categories"]):
            candidates.extend(fetch_category(category, config["max_per_category"]))
            if index + 1 < len(config["categories"]):
                time.sleep(1)
    cutoff = dt.date.today() - dt.timedelta(days=config["lookback_days"])
    unique = {p["id"]: p for p in candidates if dt.date.fromisoformat(p["published"]) >= cutoff}
    candidates = sorted(unique.values(), key=lambda p: (p["published"], p["id"]), reverse=True)
    candidates = candidates[:config["max_candidates"]]
    try:
        rankings = fallback_rank(candidates, config) if args.no_codex else codex_rank(candidates, config, args.model)
        engine = "keyword-fallback" if args.no_codex else "codex"
    except Exception as exc:
        print(f"Codex ranking failed, using fallback: {exc}", file=sys.stderr)
        rankings, engine = fallback_rank(candidates, config), "keyword-fallback"
    by_id = {r["id"]: r for r in rankings}
    today = dt.date.today().isoformat()
    fresh = []
    for paper in candidates:
        paper.update(by_id[paper["id"]])
        paper["selected_on"] = today
        if paper["score"] >= config["minimum_score"]:
            fresh.append(paper)
    fresh = sorted(fresh, key=lambda p: (p["score"], p["published"]), reverse=True)
    fresh = fresh[:config["recommend_count"]]
    history = {p["id"]: p for p in existing.get("papers", [])}
    history.update({p["id"]: p for p in fresh})
    output = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "ranking_engine": engine,
        "candidate_count": len(candidates), "recommended_today": len(fresh),
        "papers": sorted(history.values(), key=lambda p: (p["selected_on"], p["score"], p["published"]), reverse=True)[:500],
    }
    destination = ROOT / "site/data/papers.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Selected {len(fresh)}/{len(candidates)} papers with {engine}; wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
