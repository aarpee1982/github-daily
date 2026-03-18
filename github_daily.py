from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CONFIG_PATH = ROOT / "config.json"

TRENDING_URL = "https://github.com/trending"
SEARCH_URL = "https://api.github.com/search/repositories"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "github-daily"
}
if os.getenv("GH_TOKEN"):
    HEADERS["Authorization"] = f"Bearer {os.getenv('GH_TOKEN')}"

NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()


@dataclass
class RepoCandidate:
    full_name: str
    html_url: str
    description: str
    language: str | None
    stars: int
    forks: int
    open_issues: int
    watchers: int
    pushed_at: datetime
    created_at: datetime
    updated_at: datetime
    topics: list[str]
    homepage: str | None
    archived: bool
    fork: bool
    source: str
    query_match: str | None = None
    score: float = 0.0
    bucket_reason: str = ""

    @property
    def age_days(self) -> int:
        return max(1, (NOW - self.created_at).days)

    @property
    def pushed_days_ago(self) -> int:
        return max(0, (NOW - self.pushed_at).days)

    @property
    def star_velocity_proxy(self) -> float:
        return self.stars / math.sqrt(self.age_days)


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def request_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def scrape_trending() -> list[str]:
    html = request_text(TRENDING_URL)
    matches = re.findall(r'href="/([^"/]+/[^"/]+)"', html)
    seen = set()
    repos = []
    for match in matches:
        if match.count("/") != 1:
            continue
        if match in seen:
            continue
        seen.add(match)
        repos.append(match)
    return repos[:25]


def search_repos(query: str, per_page: int = 15) -> list[RepoCandidate]:
    data = request_json(SEARCH_URL, {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
        "page": 1,
    })
    items = data.get("items", [])
    results: list[RepoCandidate] = []
    for item in items:
        results.append(RepoCandidate(
            full_name=item["full_name"],
            html_url=item["html_url"],
            description=item.get("description") or "No description",
            language=item.get("language"),
            stars=item.get("stargazers_count", 0),
            forks=item.get("forks_count", 0),
            open_issues=item.get("open_issues_count", 0),
            watchers=item.get("watchers_count", 0),
            pushed_at=parse_dt(item["pushed_at"]),
            created_at=parse_dt(item["created_at"]),
            updated_at=parse_dt(item["updated_at"]),
            topics=item.get("topics") or [],
            homepage=item.get("homepage"),
            archived=item.get("archived", False),
            fork=item.get("fork", False),
            source="search",
            query_match=query,
        ))
    return results


def fetch_repo(full_name: str) -> RepoCandidate | None:
    url = f"https://api.github.com/repos/{full_name}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        return None
    item = response.json()
    return RepoCandidate(
        full_name=item["full_name"],
        html_url=item["html_url"],
        description=item.get("description") or "No description",
        language=item.get("language"),
        stars=item.get("stargazers_count", 0),
        forks=item.get("forks_count", 0),
        open_issues=item.get("open_issues_count", 0),
        watchers=item.get("subscribers_count") or item.get("watchers_count", 0),
        pushed_at=parse_dt(item["pushed_at"]),
        created_at=parse_dt(item["created_at"]),
        updated_at=parse_dt(item["updated_at"]),
        topics=item.get("topics") or [],
        homepage=item.get("homepage"),
        archived=item.get("archived", False),
        fork=item.get("fork", False),
        source="trending",
    )


def normalize_text(text: str) -> str:
    return (text or "").lower().strip()


def is_excluded(repo: RepoCandidate, config: dict[str, Any]) -> bool:
    text = f"{repo.full_name} {repo.description}".lower()
    if repo.archived or repo.fork:
        return True
    return any(term.lower() in text for term in config["exclude_terms"])


def relevance_score(repo: RepoCandidate, config: dict[str, Any]) -> float:
    score = 0.0
    hay = f"{repo.full_name} {repo.description} {' '.join(repo.topics)}".lower()
    for topic in config["topics"]:
        if topic.lower() in hay:
            score += 1.2
    for q in config["watch_queries"]:
        for word in q.lower().split():
            if len(word) > 3 and word in hay:
                score += 0.15
    if repo.language in config["languages"]:
        score += 0.8
    return score


def maintenance_score(repo: RepoCandidate) -> float:
    pushed_days = repo.pushed_days_ago
    if pushed_days <= 7:
        return 4.0
    if pushed_days <= 30:
        return 3.0
    if pushed_days <= 60:
        return 2.0
    if pushed_days <= 120:
        return 1.0
    return -1.5


def quality_proxy(repo: RepoCandidate) -> float:
    score = 0.0
    if repo.description and repo.description != "No description":
        score += 0.6
    if repo.homepage:
        score += 0.2
    if repo.forks >= 50:
        score += 0.6
    if repo.watchers >= 10:
        score += 0.4
    return score


def breakout_score(repo: RepoCandidate, config: dict[str, Any]) -> float:
    return (
        3.5 * math.log10(max(repo.star_velocity_proxy, 1)) +
        1.4 * maintenance_score(repo) +
        1.2 * relevance_score(repo, config) +
        0.8 * quality_proxy(repo)
    )


def sustained_score(repo: RepoCandidate, config: dict[str, Any]) -> float:
    return (
        1.8 * math.log10(max(repo.stars, 1)) +
        1.8 * math.log10(max(repo.star_velocity_proxy, 1)) +
        1.5 * maintenance_score(repo) +
        1.4 * relevance_score(repo, config) +
        0.8 * quality_proxy(repo)
    )


def durable_score(repo: RepoCandidate, config: dict[str, Any]) -> float:
    return (
        2.8 * math.log10(max(repo.stars, 1)) +
        1.2 * math.log10(max(repo.forks + 1, 1)) +
        1.4 * maintenance_score(repo) +
        1.0 * relevance_score(repo, config) +
        0.8 * quality_proxy(repo)
    )


def verdict(repo: RepoCandidate) -> str:
    if repo.pushed_days_ago <= 14 and repo.star_velocity_proxy > 300:
        return "Test now"
    if repo.pushed_days_ago <= 45:
        return "Sandbox later"
    return "Learn from it"


def one_liner(repo: RepoCandidate) -> str:
    desc = repo.description.strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)
    return desc[:180]


def fmt_repo(repo: RepoCandidate) -> str:
    return (
        f"### {repo.full_name}\n"
        f"{repo.html_url}\n\n"
        f"- What it is: {one_liner(repo)}\n"
        f"- Why it matters now: {repo.bucket_reason}\n"
        f"- Evidence: {repo.stars:,} stars, {repo.forks:,} forks, pushed {repo.pushed_days_ago} days ago, language {repo.language or 'Unknown'}\n"
        f"- Verdict: {verdict(repo)}\n"
    )


def dedupe(candidates: list[RepoCandidate]) -> list[RepoCandidate]:
    best: dict[str, RepoCandidate] = {}
    for repo in candidates:
        current = best.get(repo.full_name)
        if current is None or repo.score > current.score:
            best[repo.full_name] = repo
    return list(best.values())


def build_buckets(config: dict[str, Any]) -> dict[str, list[RepoCandidate]]:
    candidates: list[RepoCandidate] = []

    for full_name in scrape_trending():
        repo = fetch_repo(full_name)
        if repo and not is_excluded(repo, config):
            repo.score = breakout_score(repo, config)
            repo.bucket_reason = "Trending now and still active, which makes it a genuine breakout candidate."
            candidates.append(repo)

    created_after = (NOW - timedelta(days=365 * 2)).date().isoformat()
    pushed_after = (NOW - timedelta(days=config["recent_push_days"])).date().isoformat()
    durable_pushed_after = (NOW - timedelta(days=config["durable_push_days"])).date().isoformat()

    for query in config["watch_queries"]:
        q = f'{query} stars:>={config["min_stars_sustained"]} pushed:>={pushed_after} archived:false'
        for repo in search_repos(q, per_page=12):
            if is_excluded(repo, config):
                continue
            repo.score = sustained_score(repo, config)
            repo.bucket_reason = f"Strong search match for {query} with recent activity and enough baseline traction."
            candidates.append(repo)

    for lang in config["languages"]:
        q = f'language:{lang} created:>={created_after} stars:>={config["min_stars_sustained"]} archived:false'
        for repo in search_repos(q, per_page=10):
            if is_excluded(repo, config):
                continue
            repo.score = sustained_score(repo, config)
            repo.bucket_reason = f"Strong newer repo in {lang} with enough stars to deserve a medium-term look."
            candidates.append(repo)

    for topic in config["topics"][:6]:
        q = f'topic:{topic} stars:>={config["min_stars_durable"]} pushed:>={durable_pushed_after} archived:false'
        for repo in search_repos(q, per_page=10):
            if is_excluded(repo, config):
                continue
            repo.score = durable_score(repo, config)
            repo.bucket_reason = f"Already trusted by the market and still active in a theme you care about: {topic}."
            candidates.append(repo)

    all_candidates = dedupe(candidates)

    breakouts = [r for r in all_candidates if r.source == "trending"]
    for r in breakouts:
        r.score = breakout_score(r, config)
    breakouts = sorted(breakouts, key=lambda x: x.score, reverse=True)[:config["max_results_per_bucket"]]

    sustained = [
        r for r in all_candidates
        if r.full_name not in {b.full_name for b in breakouts}
        and r.stars >= config["min_stars_sustained"]
        and r.pushed_days_ago <= config["recent_push_days"]
    ]
    for r in sustained:
        r.score = sustained_score(r, config)
    sustained = sorted(sustained, key=lambda x: x.score, reverse=True)[:config["max_results_per_bucket"]]

    durable = [
        r for r in all_candidates
        if r.full_name not in {b.full_name for b in breakouts + sustained}
        and r.stars >= config["min_stars_durable"]
        and r.pushed_days_ago <= config["durable_push_days"]
    ]
    for r in durable:
        r.score = durable_score(r, config)
    durable = sorted(durable, key=lambda x: x.score, reverse=True)[:config["max_results_per_bucket"]]

    watchlist = [
        r for r in all_candidates
        if r.full_name not in {b.full_name for b in breakouts + sustained + durable}
        and relevance_score(r, config) >= 1.6
    ]
    for r in watchlist:
        r.score = sustained_score(r, config) + 1.0
        if not r.bucket_reason:
            r.bucket_reason = "High relevance to your chosen themes."
    watchlist = sorted(watchlist, key=lambda x: x.score, reverse=True)[:config["max_results_per_bucket"]]

    return {
        "breakouts": breakouts,
        "sustained": sustained,
        "durable": durable,
        "watchlist": watchlist,
    }


def write_report(buckets: dict[str, list[RepoCandidate]]) -> None:
    total = sum(len(v) for v in buckets.values())
    lines = [
        f"# GitHUB daily - {TODAY}",
        "",
        "This issue ranks repositories across four buckets so the list is usable rather than noisy.",
        "",
        "## How to read this",
        "",
        "- Breakouts catch unusual present-moment momentum.",
        "- Sustained movers filter for projects that still matter after the first excitement wave.",
        "- Durable greats surface infrastructure-grade repos that remain maintained.",
        "- Watchlist hits are direct matches for your themes.",
        "",
        f"Total repos highlighted today: {total}",
        "",
        "## Breakouts",
        "",
    ]

    for repo in buckets["breakouts"]:
        lines.append(fmt_repo(repo))

    lines.extend(["", "## Sustained movers", ""])
    for repo in buckets["sustained"]:
        lines.append(fmt_repo(repo))

    lines.extend(["", "## Durable greats", ""])
    for repo in buckets["durable"]:
        lines.append(fmt_repo(repo))

    lines.extend(["", "## Watchlist hits", ""])
    for repo in buckets["watchlist"]:
        lines.append(fmt_repo(repo))

    lines.extend([
        "",
        "## Operating note",
        "",
        "A starred repo is not automatically a useful repo. Prioritize testing workflows that remove real friction in your work.",
    ])

    (OUTPUT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    config = load_config()
    buckets = build_buckets(config)
    write_report(buckets)
    print(f"Wrote {OUTPUT_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
