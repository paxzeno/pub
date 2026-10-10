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
