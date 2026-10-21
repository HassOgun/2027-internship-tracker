#!/usr/bin/env python3
"""Generate an MIS-focused TOP20.md from the existing internship feed."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'listings.json'
OUTPUT = ROOT / 'TOP20.md'

ROLE_PATTERNS = [
    (r'\bbusiness (systems? )?analyst\b|\bbusiness technology analyst\b', 10, 'Business Analysis'),
    (r'\b(it|information systems?|information technology|technology|systems?) analyst\b', 9.5, 'IT / Information Systems'),
    (r'\b(technology|tech|digital|it) consult(ing|ant)\b', 9, 'Technology Consulting'),
    (r'\b(erp|sap|enterprise (applications?|systems?))\b', 8.8, 'ERP / SAP'),
    (r'\b(it|technical|technology|digital) project (management|manager|coordinator)\b|\bproject management intern\b', 8.4, 'IT Project Management'),
    (r'\b(data|business intelligence|bi|reporting|analytics) analyst\b|\bbusiness intelligence\b', 8.2, 'Data / BI'),
    (r'\b(supply chain|operations|process|continuous improvement) analyst\b', 7.2, 'Operations'),
    (r'\bproduct (management|manager|analyst)\b', 6.5, 'Product'),
]
EXCLUDE = re.compile(r'\b(senior|staff|principal|lead|director)\b', re.I)
TECH_ONLY = re.compile(r'\b(software engineer|frontend|front.end|back.end|full.stack|hardware engineer|quantitative researcher|quant trader)\b', re.I)


def role_match(title):
    for pattern, points, category in ROLE_PATTERNS:
        if re.search(pattern, title, re.I):
            return points, category
    return None


def freshness(ts, today):
    if not isinstance(ts, (int, float)):
        return 0.0, 'Unknown'
    try:
        posted = datetime.fromtimestamp(ts, timezone.utc).date()
        age = max(0, (today - posted).days)
        return (3 if age <= 3 else 2 if age <= 7 else 1 if age <= 14 else 0), str(posted)
    except (ValueError, OverflowError, OSError):
        return 0.0, 'Unknown'


def safe_cell(value):
    return str(value or '').replace('|', '\\|').replace('\n', ' ').strip()


def location_priority(locations):
    """Prefer Houston and US remote; avoid clearly international-only roles."""
    parts = [str(x).strip() for x in locations if str(x).strip()]
    combined = ', '.join(parts)
    us_remote = re.compile(r'\bremote\b.*\b(us|usa|united states|u\.s\.)\b|\b(us|usa|united states|u\.s\.)\b.*\bremote\b', re.I)
    houston = re.compile(r'\b(houston|katy|cypress|sugar land|the woodlands|spring|pearland|richmond|missouri city)\b', re.I)
    texas = re.compile(r'\b(texas|\btx\b|dallas|austin|san antonio|fort worth|plano)\b', re.I)
    international = re.compile(r'\b(canada|montreal|ottawa|toronto|vancouver|quebec|ontario|\bqc\b|\bon\b|united kingdom|london|india|germany|france|singapore|australia)\b', re.I)
    us = re.compile(r'\b(usa|united states|u\.s\.|new york|nyc|seattle|kirkland|washington|california|boston|chicago|atlanta|florida|colorado)\b', re.I)
    if houston.search(combined):
        return 2.5
    if us_remote.search(combined):
        return 2.25
    if texas.search(combined):
        return 1.25
    if re.search(r'\bremote\b', combined, re.I) and not international.search(combined):
        return 1.5  # Remote, geography not specified: verify eligibility
    if us.search(combined):
        return 0.25
    if parts and all(international.search(part) and not us.search(part) for part in parts):
        return None  # Clearly international-only
    return 0.0  # Unknown geography: retain, but rank lower


def main():
    if not DATA.exists():
        raise SystemExit('Missing data/listings.json: run scrape.py first')
    listings = json.loads(DATA.read_text(encoding='utf-8'))
    today = datetime.now(timezone.utc).date()
    candidates = []
    for listing in listings:
        if not listing.get('active', True) or not listing.get('is_visible', True):
            continue
        title = str(listing.get('title') or '')
        if EXCLUDE.search(title) or TECH_ONLY.search(title):
            continue
        match = role_match(title)
        if not match:
            continue
        role_score, category = match
        locations = listing.get('locations') or []
        location = ', '.join(map(str, locations))
        location_score = location_priority(locations)
        if location_score is None:
            continue
        fresh_score, posted = freshness(listing.get('date_posted'), today)
        score = role_score + location_score + fresh_score
        candidates.append((score, listing, category, posted, location))
    candidates.sort(key=lambda item: item[0], reverse=True)
    picks, seen = [], set()
    for score, listing, category, posted, location in candidates:
        company = str(listing.get('company_name') or '').strip()
        if not company or company.casefold() in seen:
            continue
        seen.add(company.casefold())
        picks.append((listing, category, posted, location))
        if len(picks) == 20:
            break
    lines = [f'# MIS Internship Top 20 — {today}', '',
             'Ranked by role relevance, posting freshness, and Houston-first location preference, with US remote and other Texas roles also prioritized.', '',
             '> Listings come from the existing tracker feeds. Verify eligibility, graduation requirements, and whether applications are still open on the employer site.', '',
             f'**{len(picks)} matches selected** from {len(candidates)} relevant active listings.', '',
             '| # | Company | Role | Category | Location | Posted | Apply |',
             '|---|---|---|---|---|---|---|']
    for index, (listing, category, posted, location) in enumerate(picks, 1):
        url = str(listing.get('url') or '').strip()
        link = f'[Apply]({url})' if url.startswith(('https://', 'http://')) else '—'
        lines.append(f"| {index} | {safe_cell(listing.get('company_name'))} | {safe_cell(listing.get('title'))} | {category} | {safe_cell(location)} | {posted} | {link} |")
    if not picks:
        lines.append('| — | No matching roles in current feeds | — | — | — | — | — |')
    lines.extend(['', f'*Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}.*', ''])
    OUTPUT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Generated {len(picks)} MIS-focused recommendations from {len(candidates)} relevant listings')


if __name__ == '__main__':
    main()
