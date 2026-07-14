#!/usr/bin/env python3
"""Generate a standalone auditable HTML report from validated prospect JSON."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from report_model import DIMENSION_WEIGHTS, ReportValidationError, load_and_audit


SKILL_ROOT = Path(__file__).resolve().parents[1]
STYLESHEET = SKILL_ROOT / "assets" / "report.css"

DIMENSION_LABELS = {
    "pain_strength": "Pain strength",
    "product_fit": "Product fit",
    "timing": "Timing",
    "reachability": "Reachability",
    "evidence_quality": "Evidence quality",
}


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def safe_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return esc(raw)
    return None


def render_link(url: Any, label: Any, class_name: str = "") -> str:
    safe = safe_url(url)
    if not safe:
        return f'<span class="{esc(class_name)}">{esc(label)}</span>'
    class_attr = f' class="{esc(class_name)}"' if class_name else ""
    return (
        f'<a{class_attr} href="{safe}" target="_blank" rel="noopener noreferrer">'
        f"{esc(label)} ↗</a>"
    )


def render_text_list(values: list[Any], empty: str = "None recorded") -> str:
    if not values:
        return f"<p class=\"muted\">{esc(empty)}</p>"
    return "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>"


def render_profile(title: str, profile: dict[str, Any]) -> str:
    rows = [
        ("User", profile["user"]),
        ("Buyer", profile["buyer"]),
        ("Job", profile["job"]),
        ("Trigger", profile["trigger"]),
        ("Current alternative", profile["current_alternative"]),
    ]
    body = "".join(
        f'<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>' for label, value in rows
    )
    return f'<article class="profile card"><p class="kicker">{esc(title)}</p><dl>{body}</dl></article>'


def render_dimensions(dimensions: dict[str, int]) -> str:
    metrics = []
    for key in DIMENSION_WEIGHTS:
        score = dimensions[key]
        metrics.append(
            '<div class="metric">'
            f"<span>{esc(DIMENSION_LABELS[key])}</span>"
            f'<div class="track"><i style="width:{score * 20}%"></i></div>'
            f"<b>{score}/5</b>"
            "</div>"
        )
    return "".join(metrics)


def render_sources(sources: list[dict[str, Any]]) -> str:
    cards = []
    for source in sources:
        published = source["published_at"] or "Date unavailable"
        cards.append(
            '<article class="source">'
            f'<div><span class="source-type">{esc(source["type"])}</span>'
            f"<h4>{render_link(source['url'], source['title'])}</h4></div>"
            f'<p>{esc(source["evidence"])}</p>'
            f'<footer><span>Published: {esc(published)}</span><span>Checked: {esc(source["checked_at"])}</span></footer>'
            "</article>"
        )
    return "".join(cards)


def render_prospect(prospect: dict[str, Any], rank: int) -> str:
    contact = prospect["contact"]
    outreach = prospect["outreach"]
    contact_route = (
        render_link(contact["route_url"], contact["route_type"])
        if contact["route_url"]
        else esc(contact["route_type"])
    )
    inferred = render_text_list(prospect["evidence"]["inferred"], "No inference recorded")
    return f"""
    <article class="prospect card" id="{esc(prospect['id'])}">
      <header class="prospect-head">
        <div class="rank">{rank:02d}</div>
        <div class="identity"><p class="kicker">{esc(prospect['type'])} · {esc(prospect['stage'])}</p><h3>{esc(prospect['name'])}</h3></div>
        <div class="score" style="--score:{prospect['score']}" aria-label="Score {prospect['score']} out of 100"><strong>{prospect['score']}</strong><small>/100</small></div>
      </header>
      <div class="signal"><span>Public signal</span><p>{esc(prospect['pain_signal'])}</p></div>
      <div class="two-up">
        <section><h4>Why it fits</h4><p>{esc(prospect['why_fit'])}</p></section>
        <section><h4>Why now</h4><p>{esc(prospect['why_now'])}</p></section>
      </div>
      <div class="audit-grid">
        <section><h4>Observed</h4>{render_text_list(prospect['evidence']['observed'])}</section>
        <section><h4>Inferred</h4>{inferred}</section>
      </div>
      <section class="sources"><h4>Original evidence</h4>{render_sources(prospect['sources'])}</section>
      <details>
        <summary>Score breakdown</summary>
        <div class="metrics">{render_dimensions(prospect['dimensions'])}</div>
      </details>
      <div class="contact-strip">
        <div><span>Target role</span><strong>{esc(contact['target_role'])}</strong></div>
        <div><span>Public route</span><strong>{contact_route}</strong></div>
        <div><span>Route rationale</span><p>{esc(contact['rationale'])}</p></div>
      </div>
      <blockquote><span>Manual opener</span><p>{esc(outreach['opener'])}</p></blockquote>
      <div class="outreach-grid">
        <div><span>Offer</span><p>{esc(outreach['offer'])}</p></div>
        <div><span>CTA</span><p>{esc(outreach['cta'])}</p></div>
        <div><span>Likely objection</span><p>{esc(outreach['likely_objection'])}</p></div>
        <div><span>Caution</span><p>{esc(prospect['caution'])}</p></div>
      </div>
    </article>"""


def render_patterns(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return '<p class="empty">No repeated pattern met the evidence threshold.</p>'
    return "".join(
        '<article class="pattern card">'
        f'<strong>{pattern["count"]}×</strong><div><h3>{esc(pattern["title"])}</h3>'
        f'<p>{esc(pattern["insight"])}</p><small>Evidence: {esc(", ".join(pattern["supporting_prospect_ids"]))}</small></div>'
        "</article>"
        for pattern in patterns
    )


def render_plan(plan: dict[str, Any]) -> str:
    steps = "".join(
        '<article class="plan-step">'
        f'<div class="day">Day {step["day"]}</div><div><p>{esc(step["action"])}</p>'
        f'<small>Success: {esc(step["success_signal"])}</small></div></article>'
        for step in sorted(plan["steps"], key=lambda item: item["day"])
    )
    return f"""
    <section class="plan card">
      <div class="plan-intro"><p class="kicker">Manual validation plan</p><h2>{esc(plan['angle'])}</h2><p><strong>Success metric:</strong> {esc(plan['success_metric'])}</p></div>
      <div class="plan-steps">{steps}</div>
    </section>"""


def build_html(data: dict[str, Any], css: str) -> str:
    prospects = data["prospects"]
    scores = [prospect["score"] for prospect in prospects]
    average = round(sum(scores) / len(scores)) if scores else 0
    high_intent = sum(prospect["stage"] == "high-intent" for prospect in prospects)
    top = prospects[0] if prospects else None
    product = data["product"]
    product_name = render_link(product["url"], product["name"]) if product["url"] else esc(product["name"])
    source_count = sum(len(prospect["sources"]) for prospect in prospects)
    top_html = (
        f'<div><p class="kicker">Highest-confidence prospect</p><h2>{esc(top["name"])}</h2><p>{esc(top["why_now"])}</p></div><strong>{top["score"]}</strong>'
        if top
        else '<div><p class="kicker">Research result</p><h2>No qualified prospects</h2><p>Refine the ICP or expand the public-source scope.</p></div>'
    )
    prospect_html = "".join(render_prospect(item, index) for index, item in enumerate(prospects, 1))
    rationale = render_text_list(data["verdict"]["rationale"])
    limitations = render_text_list(data["limitations"])
    disqualifiers = render_text_list(data["icp"]["disqualifiers"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>{esc(data['title'])}</title>
  <style>{css}</style>
</head>
<body>
  <a class="skip" href="#main">Skip to report</a>
  <div class="shell">
    <header class="topbar"><div class="brand"><i></i> Find First Customers</div><div><span class="badge">Public signals only</span><span class="badge">Print-ready</span></div></header>
    <main id="main">
      <section class="hero">
        <div><p class="kicker">Early-customer intelligence · {esc(data['generated_at'])}</p><h1>{esc(data['title'])}</h1><p class="lede">{esc(data['verdict']['summary'])}</p></div>
        <aside><span>Qualified prospects</span><strong>{len(prospects)}</strong><p>{esc(data['verdict']['confidence'])} confidence</p></aside>
      </section>
      <section class="stats card">
        <div><span>Product</span><strong>{product_name}</strong></div><div><span>Depth · focus</span><strong>{esc(data['mode'])} · {esc(data['focus'])}</strong></div><div><span>High intent</span><strong>{high_intent}</strong></div><div><span>Average score</span><strong>{average}/100</strong></div><div><span>Original sources</span><strong>{source_count}</strong></div>
      </section>
      <section class="top-prospect">{top_html}</section>
      <section class="section">
        <header class="section-head"><div><p class="kicker">Product and market</p><h2>Who has the job—and why now?</h2></div><p>{esc(product['summary'])} {esc(product['outcome'])}</p></header>
        <div class="profiles">{render_profile('Primary ICP', data['icp']['primary'])}{render_profile('Adjacent ICP', data['icp']['adjacent'])}</div>
        <div class="context-grid card"><div><h3>Disqualifiers</h3>{disqualifiers}</div><div><h3>Research scope</h3><p>{esc(data['research']['scope'])}</p><small>Searched {esc(data['research']['searched_at'])} · {esc(', '.join(data['research']['source_types']))}</small></div><div><h3>Verdict rationale</h3>{rationale}</div></div>
      </section>
      <section class="section">
        <header class="section-head"><div><p class="kicker">Qualified shortlist</p><h2>People with a public reason to care.</h2></div><p>Scores are calculated from documented dimensions. Every candidate links to original evidence.</p></header>
        <div class="prospects">{prospect_html or '<p class="empty">No prospect cleared the qualification threshold.</p>'}</div>
      </section>
      <section class="section">
        <header class="section-head"><div><p class="kicker">Repeated evidence</p><h2>Signals that shape positioning.</h2></div></header>
        <div class="patterns">{render_patterns(data['patterns'])}</div>
      </section>
      {render_plan(data['outreach_plan'])}
      <section class="limitations card"><p class="kicker">Research limitations</p><h2>What still needs a conversation.</h2>{limitations}</section>
    </main>
    <footer class="page-footer"><span>Generated by $find-first-customers</span><span>Potential customers based on public signals—not confirmed buyers.</span></footer>
  </div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Validated or source analysis JSON")
    parser.add_argument("output", type=Path, help="Output HTML file")
    args = parser.parse_args()

    try:
        result = load_and_audit(args.input)
    except ReportValidationError as error:
        print(error, file=sys.stderr)
        return 1

    if not STYLESHEET.is_file():
        print(f"Missing report stylesheet: {STYLESHEET}", file=sys.stderr)
        return 1
    css = STYLESHEET.read_text(encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(result.data, css), encoding="utf-8")
    for warning in result.warnings:
        print(warning)
    print(f"Created report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
