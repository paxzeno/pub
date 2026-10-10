"""Conservative English offer-range extraction; no inferred year or timezone."""
import re
from datetime import date, datetime, timedelta, timezone

MONTHS = {name.lower(): i for i, names in enumerate([
    ('Jan','January'),('Feb','February'),('Mar','March'),('Apr','April'),('May','May'),
    ('Jun','June'),('Jul','July'),('Aug','August'),('Sep','September'),('Oct','October'),
    ('Nov','November'),('Dec','December')], 1) for name in names}
MONTH = '(' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + ')'


def extract_offer_timing(body):
    # Require an explicit offer period and year, not an unrelated publication date.
    pattern = r'(?:offer valid|promotional period|valid from)[^.\n]{0,120}?' + MONTH + r'\s+(\d{1,2})\s*[–—-]\s*(\d{1,2}),?\s+(20\d{2})'
    matches = list(re.finditer(pattern, body, re.I))
    if len(matches) != 1:
        return {}
    hit = matches[0]
    month, start, end, year = hit.groups()
    try:
        end_date = date(int(year), MONTHS[month.lower()], int(end))
        date(int(year), MONTHS[month.lower()], int(start))
        if int(start) > int(end):
            return {}
    except ValueError:
        return {}
    evidence = hit[0]
    # A second explicit end-time clause must match that exact month and end day.
    ends = list(re.finditer(r'[–—-]\s*' + MONTH + r'\s+(\d{1,2}),?\s+(\d{1,2}):(\d{2})\s+(CEST|CET|UTC|GMT)\b', body, re.I))
    compatible = [m for m in ends if MONTHS[m[1].lower()] == end_date.month and int(m[2]) == end_date.day]
    if len(compatible) == 1:
        t = compatible[0]
        offset = {'CEST':2,'CET':1,'UTC':0,'GMT':0}[t[5].upper()]
        try:
            dt = datetime(end_date.year,end_date.month,end_date.day,int(t[3]),int(t[4]),tzinfo=timezone(timedelta(hours=offset)))
        except ValueError:
            return {}
        return {'deadline':dt.isoformat(),'deadline_evidence':evidence+'\n'+t[0], 'deadline_date':None}
    return {'deadline':None,'deadline_date':end_date.isoformat(),'deadline_evidence':evidence}


def extract_event_timing(body, subject=''):
    """Extract one explicit event range; subject year may qualify a yearless range.

    Never use the receipt/current year, nor an unrelated year elsewhere in the body.
    Ambiguous multiple ranges are left unresolved.
    """
    source = re.sub(r'\s+', ' ', body).strip()
    pattern = MONTH + r'\s+(\d{1,2})\s*(?:[–—-]|to)\s*(\d{1,2})(?:,?\s+(20\d{2}))?\b'
    candidates = []
    for hit in re.finditer(pattern, source, re.I):
        context = source[max(0, hit.start()-160):hit.start()]
        if not re.search(r'\b(?:find us at|event|tournament|conference|festival|visit our booth)\b', context, re.I):
            continue
        month, start, end, year = hit.groups()
        evidence = source[max(0, hit.start()-160):hit.end()]
        if not year:
            years = set(re.findall(r'\b20\d{2}\b', subject))
            if len(years) != 1:
                continue
            year = years.pop()
            evidence = subject + '\n' + evidence
        try:
            first = date(int(year), MONTHS[month.lower()], int(start))
            last = date(int(year), MONTHS[month.lower()], int(end))
        except ValueError:
            continue
        if first <= last:
            candidates.append({'start':first.isoformat(), 'end':last.isoformat(), 'evidence':evidence})
    single = MONTH + r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b'
    for hit in re.finditer(single, source, re.I):
        context = source[max(0, hit.start()-160):hit.start()]
        if not re.search(r'\b(?:webinar|live session|event|conference|festival)\b', context, re.I):
            continue
        month, day, year = hit.groups()
        try:
            value = date(int(year), MONTHS[month.lower()], int(day)).isoformat()
        except ValueError:
            continue
        candidates.append({'start':value,'end':value,'evidence':context+hit[0]})
    unique = {(d['start'],d['end']):d for d in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def unresolved_timing_notice(body, subject=''):
    """Keep literal dates/urgency visible without inventing a year or cutoff."""
    source = re.sub(r'\s+', ' ', subject + ' ' + body)
    date_hit = re.search(r'\b' + MONTH + r'\s+\d{1,2}(?:st|nd|rd|th)?\b(?:\s*[•,–-]?\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:PT|ET|UTC|GMT)(?:\s*/\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:PT|ET|UTC|GMT))?)?', source, re.I)
    if date_hit and re.search(r'\b(?:webinar|live session|event|join us|register)\b', source, re.I):
        return 'Source event timing: “' + date_hit[0] + '”; full date/year not verified.'
    urgency = re.search(r"won[’']t last(?: forever| long)?|ending soon|ends soon|limited[ -]time", source, re.I)
    if urgency:
        return 'Source urgency: “' + urgency[0] + '”; exact cutoff not supplied.'
    return ''
