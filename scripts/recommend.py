#!/usr/bin/env python3
"""Generate MIS-focused TOP20.md from data/listings.json (stdlib only)."""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'listings.json'
OUTPUT = ROOT / 'TOP20.md'

ROLE_PATTERNS = [
    (r'\bbusiness systems? analyst\b|\bbusiness analyst\b|\bbusiness technology analyst\b|\bfunctional analyst\b', 10, 'Business Analysis'),
    (r'\b(it|information systems?|information technology|technology|systems?|business systems?) analyst\b|\bit (intern|internship)\b|\binformation technology intern\b|\btechnology operations intern\b', 9.5, 'IT / Information Systems'),
    (r'\b(technology|tech|digital|it|management) consult(?:ing|ant|ancy)\b|\bconsulting (intern|analyst)\b', 9, 'Technology Consulting'),
    (r'\b(erp|sap|workday|oracle erp|enterprise (applications?|systems?))\b', 8.8, 'ERP / SAP'),
    (r'\b(it|technical|technology|digital|information systems?) project (management|manager|coordinator)\b|\bproject management (intern|analyst)\b|\bproject coordinator\b|\bprogram management intern\b', 8.4, 'IT Project Management'),
    (r'\b(data|business intelligence|bi|reporting|analytics|insights) analyst\b|\bbusiness intelligence\b|\bpower bi\b|\bdata analytics? intern\b|\breporting intern\b', 8.2, 'Data / BI'),
    (r'\b(supply chain|operations|process|continuous improvement|business operations|operational excellence) (analyst|intern)\b|\bdigital transformation\b', 7.2, 'Operations / Transformation'),
    (r'\bproduct (management|manager|analyst|operations)\b', 6.5, 'Product'),
]
EXCLUDE = re.compile(r'\b(senior|staff|principal|director|vice president|vp|head of)\b', re.I)
TECH_ONLY = re.compile(r'\b(software engineer|software development engineer|frontend|front.end|back.end|full.stack|hardware engineer|quantitative researcher|quant trader)\b', re.I)
HOUSTON = re.compile(r'\b(houston|katy|cypress|sugar land|the woodlands|spring|pearland|missouri city|stafford|bellaire|pasadena|baytown|tomball|conroe|fulshear)\b', re.I)
TEXAS = re.compile(r'\b(texas|tx|dallas|austin|san antonio|fort worth|plano|frisco|irving|arlington|round rock)\b', re.I)
REMOTE = re.compile(r'\bremote\b', re.I)
US = re.compile(r'\b(us|usa|united states|u\.s\.|america|united states of america)\b', re.I)
FOREIGN = re.compile(r'\b(canada|toronto|vancouver|montreal|ottawa|quebec|ontario|united kingdom|london|india|germany|france|singapore|australia|mexico|europe|emea|apac)\b', re.I)
US_CITY = re.compile(r'\b(new york|seattle|boston|chicago|atlanta|san francisco|los angeles|denver|washington dc|california|florida|colorado|massachusetts|georgia|illinois|virginia|north carolina)\b', re.I)


def role_match(title):
    matches = [(points, category) for pattern, points, category in ROLE_PATTERNS if re.search(pattern, title, re.I)]
    return max(matches, default=None, key=lambda item: item[0])


def posted_date(value, today):
    try:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            if value > 1e11:
                value /= 1000
            dt = datetime.fromtimestamp(value, timezone.utc).date()
        elif isinstance(value, str) and value.strip():
            s = value.strip()
            if re.fullmatch(r'\d{10,13}', s):
                return posted_date(int(s), today)
            dt = datetime.fromisoformat(s.replace('Z', '+00:00')).date()
        else:
            return None
        if dt < today - timedelta(days=730) or dt > today + timedelta(days=2):
            return None
        return dt
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def freshness(value, today):
    dt = posted_date(value, today)
    if dt is None:
        return 0, 'Unknown'
    age = max(0, (today - dt).days)
    return (3 if age <= 3 else 2 if age <= 7 else 1 if age <= 14 else 0), str(dt)


def location_priority(locations):
    if isinstance(locations, str):
        locations = [locations]
    parts = [str(x).strip() for x in (locations or []) if x]
    combined = ' | '.join(parts)
    if HOUSTON.search(combined) or re.search(r'\brichmond\s*,?\s*(?:tx|texas)\b', combined, re.I):
        return 5.0, 'Houston area'
    if REMOTE.search(combined) and US.search(combined):
        return 4.5, 'US remote'
    if TEXAS.search(combined):
        return 3.0, 'Other Texas'
    if REMOTE.search(combined) and not FOREIGN.search(combined):
        return 2.0, 'Remote — verify US eligibility'
    if parts and all(FOREIGN.search(p) and not (US.search(p) or US_CITY.search(p)) for p in parts):
        return None, 'International only'
    if US.search(combined) or US_CITY.search(combined):
        return 1.0, 'Other US'
    return 0.0, 'Location — verify'


def normalized_url(value):
    url = str(value or '').strip()
    if not url.startswith(('https://', 'http://')):
        return ''
    try:
        parts = urlsplit(url)
        if not parts.hostname:
            return ''
        # Remove tracking parameters, retain job identifiers and other meaningful query parameters.
        params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                  if not (k.lower().startswith('utm_') or k.lower() in {'ref', 'referrer', 'source', 'gh_src', 'trk', 'trackingid', 'embed'})]
        path = re.sub(r'/application/?$', '', parts.path.rstrip('/'), flags=re.I) if parts.hostname.lower() == 'jobs.ashbyhq.com' else parts.path.rstrip('/')
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix('www.'),
                           path, urlencode(sorted(params)), ''))
    except ValueError:
        return ''


def safe_cell(value):
    return str(value or '').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').strip()


def main():
    if not DATA.exists():
        raise SystemExit('Missing data/listings.json: run scrape.py first')
    listings = json.loads(DATA.read_text(encoding='utf-8'))
    if not isinstance(listings, list):
        raise SystemExit('Expected data/listings.json to contain a JSON list')
    today = datetime.now(timezone.utc).date()
    candidates = []
    for item in listings:
        if not isinstance(item, dict) or item.get('active', True) is False or item.get('is_visible', True) is False:
            continue
        title = str(item.get('title') or '').strip()
        if not title or EXCLUDE.search(title) or TECH_ONLY.search(title) or re.search(r'\bwith drexel university\b', title, re.I):
            continue
        match = role_match(title)
        if not match:
            continue
        company = str(item.get('company_name') or '').strip()
        if not company:
            continue
        locs = item.get('locations') or []
        location_score, location_label = location_priority(locs)
        if location_score is None:
            continue
        if isinstance(locs, str):
            locs = [locs]
        location = ', '.join(str(x) for x in locs)
        fresh_score, posted = freshness(item.get('date_posted'), today)
        # Role relevance is the primary factor; location breaks close matches.
        score = match[0] * 2 + location_score + fresh_score
        url = normalized_url(item.get('url'))
        candidates.append((score, item, match[1], posted, location, location_label, url))
    candidates.sort(key=lambda x: (-{'Houston area': 5, 'US remote': 4.5, 'Other Texas': 3, 'Remote — verify US eligibility': 2, 'Other US': 1, 'Location — verify': 0}.get(x[5], 0), -x[0], x[1].get('company_name', '').casefold(), x[1].get('title', '').casefold()))
    picks, seen_urls, seen_roles, company_counts = [], set(), set(), {}
    for candidate in candidates:
        _, item, _, _, _, _, url = candidate
        company = str(item['company_name']).strip().casefold()
        role_key = (company, str(item.get('title') or '').strip().casefold())
        if (url and url in seen_urls) or role_key in seen_roles or company_counts.get(company, 0) >= 2:
            continue
        if url:
            seen_urls.add(url)
        seen_roles.add(role_key)
        company_counts[company] = company_counts.get(company, 0) + 1
        picks.append(candidate)
        if len(picks) >= 20:
            break
    lines = [
        f'# MIS Internship Top 20 — {today}', '',
        'Ranked by MIS role relevance, posting freshness, and location (Greater Houston, US remote, other Texas, then nationwide).', '',
        '> Verify application status, graduation-date eligibility, internship term, and remote-work restrictions on the employer site. Unknown posting dates receive no freshness bonus.', '',
        f'**{len(picks)} matches selected** from {len(candidates)} relevant active records (before recommendation deduplication).', '',
        '| # | Company | Role | Category | Location | Location status | Posted | Apply |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for index, (_, item, category, posted, location, location_label, url) in enumerate(picks, 1):
        link = f'[Apply]({url})' if url else '—'
        fields = [index, item.get('company_name'), item.get('title'), category,
                  location or 'Not specified', location_label, posted, link]
        lines.append('| ' + ' | '.join(safe_cell(v) for v in fields) + ' |')
    if not picks:
        lines.append('| — | No matching roles | — | — | — | — | — | — |')
    lines.extend(['', f'*Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}.*', ''])
    OUTPUT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Generated {len(picks)} MIS-focused recommendations from {len(candidates)} relevant active records')


if __name__ == '__main__':
    main()
