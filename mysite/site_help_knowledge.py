"""
Curated public-website content for Tool Hub /query_ai site-help answers.
Each entry maps to a page on the frontend (PUBLIC_SITE_BASE_URL + path).
"""
from __future__ import annotations

import re
from typing import List, TypedDict


class SiteHelpPage(TypedDict):
    id: str
    title: str
    path: str
    keywords: tuple[str, ...]
    summary: str


SITE_HELP_PAGES: tuple[SiteHelpPage, ...] = (
    {
        "id": "how_to_use",
        "title": "How to Use the Tools",
        "path": "/how-to-use-tools",
        "keywords": (
            "tool", "tools", "website", "how to use", "login", "four tools",
            "trends", "compare", "look up", "ask a question",
        ),
        "summary": (
            "The public site offers four tools: (1) See patterns across many cases via System Trends "
            "(/trends) — no login; (2) Look up one case in Tool Hub (/toolhub) — login required; "
            "(3) Compare results across groups (custom charts) — login required; "
            "(4) Ask a question about the letter dataset in Tool Hub — login required. "
            "Approved users request access at /access."
        ),
    },
    {
        "id": "methods_overview",
        "title": "Methods & GitHub",
        "path": "/methods",
        "keywords": (
            "methods", "dataset", "1172.1", "1172", "penal code", "data source",
            "ocr", "github", "study", "research", "public records",
        ),
        "summary": (
            "This project studies CDCR-initiated resentencing under Penal Code § 1172.1. "
            "The dataset combines CDCR tracking logs (monthly), court referral letter PDFs, "
            "and race/ethnicity PRA spreadsheets merged on CDC # or PID. PDFs are OCR'd and "
            "parsed into structured metadata. A binary success variable distinguishes favorable "
            "outcomes (reduced or released) from other outcomes. Case progression has three stages: "
            "all cases considered, letters sent to court, and cases resulting in resentencing."
        ),
    },
    {
        "id": "resentencing_laws",
        "title": "Methods — CDCR resentencing program",
        "path": "/methods",
        "keywords": (
            "law", "laws", "legal", "1172.1", "penal code", "statute", "resentencing law",
            "tell me about resentencing", "history",
        ),
        "summary": (
            "This website focuses on CDCR-initiated resentencing under California Penal Code § 1172.1 — "
            "how CDCR refers cases to courts, what the referral letters say, and what courts do afterward. "
            "It is a research and transparency tool built from Public Records Act data, not general legal advice. "
            "For broader legal history or statutes beyond this dataset, consult official legal resources; "
            "for how this project defines and measures cases, see Methods and What We Measure."
        ),
    },
    {
        "id": "what_we_measure",
        "title": "What We Are Measuring",
        "path": "/methods/what-we-measure",
        "keywords": (
            "measure", "visualize", "chart", "progression", "success rate", "report",
            "what can i", "what does the site show",
        ),
        "summary": (
            "Charts show how cases move through the system: considered → letter sent → resentenced. "
            "You can measure time reduced, outcomes by sentence type, race/ethnicity distributions, "
            "county and institution comparisons, success rates, years reduced, and cost savings. "
            "Tool Hub and trends pages aggregate case counts; users can build custom comparisons "
            "without doing manual math on raw spreadsheets."
        ),
    },
    {
        "id": "variables",
        "title": "Variables in the Data Set",
        "path": "/methods/variables",
        "keywords": (
            "variable", "variables", "field", "fields", "column", "metadata", "schema",
            "action taken", "county", "cohort",
        ),
        "summary": (
            "The variable page lists every dataset field in plain language (county, judge, case number, "
            "CDCR number, dates along the resentencing pipeline, action taken, years/days reduced, "
            "cost savings, race, ethnicity, institution, and letter-derived coded variables). "
            "Use it when you need to know what a column means before searching or asking a database question."
        ),
    },
    {
        "id": "cost_savings",
        "title": "Cost Saving Calculation Methods",
        "path": "/cost-savings",
        "keywords": (
            "cost", "savings", "fiscal", "budget", "calculated", "calculation", "unallocated",
            "marginal", "per capita", "lao", "cdcr cost", "money saved",
        ),
        "summary": (
            "Three methods estimate fiscal impact: (1) Unallocated/basic (~$8,259/person/year, 2025 CDCR) — "
            "what CDCR uses in official logs and what this site's tracking data reflects; "
            "(2) Partial/marginal (~$21,500, LAO) — includes healthcare and some staffing; "
            "(3) Full/per capita (~$127,800, LAO) — full incarceration cost, preferred by the RAD project "
            "for long-term prison-capacity analysis. The cost-savings page explains why numbers differ and "
            "shows example totals under each method."
        ),
    },
    {
        "id": "success_definition",
        "title": "Methods — success and outcomes",
        "path": "/methods",
        "keywords": (
            "success", "successful", "success rate", "favorable", "outcome", "defined", "definition",
            "how is success", "what counts as",
        ),
        "summary": (
            "In this dataset, a binary success variable marks favorable outcomes: sentence reduced or release "
            "versus all other action-taken values. Tool Hub preset questions often treat success as action taken "
            "containing resentenced, released, granted, approved, or recalled — confirm against the variable "
            "definitions page when publishing formal results. County success rates in Ask a question use "
            "metadata.action_taken and county groupings."
        ),
    },
    {
        "id": "ask_questions_help",
        "title": "Ask a question — how it works",
        "path": "/how-to-use-tools/ask-questions",
        "keywords": (
            "ask a question", "ai", "assistant", "chatbot", "query", "natural language",
        ),
        "summary": (
            "Tool Hub Ask a question sends your plain-language prompt to a backend that either queries the "
            "MySQL letter database (counts, lookups, breakdowns) or answers from public website documentation "
            "about methods and calculations. Always verify AI answers against letter PDFs or a case lookup. "
            "For one person, use Look up a case; for system counts, ask about cases, letters, or records."
        ),
    },
    {
        "id": "about",
        "title": "About Us",
        "path": "/about",
        "keywords": (
            "about", "who", "team", "project", "rad", "collaboration", "disclaimer",
        ),
        "summary": (
            "The Resentencing Accountability Dashboard (RAD) is a collaboration of students, researchers, "
            "legal advocates, practitioners, and formerly incarcerated contributors studying CDCR-initiated "
            "resentencing. The site provides information and research tools only — not legal advice. "
            "AI-generated answers may contain errors; verify before relying on them."
        ),
    },
    {
        "id": "access",
        "title": "Request access",
        "path": "/access",
        "keywords": (
            "access", "login", "magic link", "approve", "account", "sign in",
        ),
        "summary": (
            "Detailed case-level tools require approved access. Users submit a request form; approvers issue "
            "a magic link email. Public trends at /trends do not require login."
        ),
    },
)


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def select_site_help_pages(user_query: str, limit: int = 4) -> List[SiteHelpPage]:
    """Rank website help pages by keyword overlap with the user question."""
    q = (user_query or "").strip().lower()
    q_tokens = _tokenize(q)
    scored: list[tuple[int, SiteHelpPage]] = []

    for page in SITE_HELP_PAGES:
        score = 0
        for kw in page["keywords"]:
            if kw in q:
                score += 3
        kw_tokens = _tokenize(" ".join(page["keywords"]))
        score += len(q_tokens & kw_tokens)
        if score > 0:
            scored.append((score, page))

    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    if scored:
        return [p for _, p in scored[:limit]]

    # Default bundle when nothing matched strongly
    defaults = ("how_to_use", "methods_overview", "what_we_measure", "ask_questions_help")
    by_id = {p["id"]: p for p in SITE_HELP_PAGES}
    return [by_id[i] for i in defaults if i in by_id]


def format_site_help_context(pages: List[SiteHelpPage], base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    blocks = []
    for page in pages:
        url = f"{base}{page['path']}"
        blocks.append(
            f"### {page['title']}\n"
            f"URL: {url}\n"
            f"{page['summary']}\n"
        )
    return "\n".join(blocks)
