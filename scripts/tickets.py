"""Shared OCR patterns. No OCR/network/calendar access in this reference parser."""
import re
from datetime import datetime, timedelta, timezone

# A complete dated card is required. Never borrow data from the next date.
SEP = r'\s*[.\-/]\s*'
VALID_DATE = (r'(?=(?:20[0-9]{2}' + SEP + r'(?:(?:01|03|05|07|08|10|12)' + SEP
              + r'(?:0[1-9]|[12][0-9]|3[01])|(?:04|06|09|11)' + SEP
              + r'(?:0[1-9]|[12][0-9]|30)|02' + SEP + r'(?:0[1-9]|1[0-9]|2[0-8]))'
              + r'|20(?:[02468][048]|[13579][26])' + SEP + '02' + SEP + r'29)(?![0-9]))')
DATE = VALID_DATE + r'(20[0-9]{2})\s*[.\-/]\s*(0[1-9]|1[0-2])\s*[.\-/]\s*(0[1-9]|[12][0-9]|3[01])\.?'
HEADER = DATE + r'\s*(?:\([^\n()]{1,10}\)\s*)?(?:(?:[0-9]+\s*일\s*전|오늘|내일)\s*)?기차\s*승차권\s*(?:[0-9]+\s*매\s*)?'
STATION = r'([가-힣]{1,12})'
TIME = r'([01][0-9]|2[0-3]):([0-5][0-9])'
# Vision returns screen text in spatial order, so filter chips and tab-bar labels land
# between a card header and its stations. Skipping digit-free lines only is what keeps the
# rule from reaching into the next card: every date and time line carries digits.
NOISE = r'(?:[^\n0-9]*\n)*?'
# The grey arrow between stations comes back as anything from '→' to 'ㅗ'. Accept whatever is
# not a Hangul syllable or a digit instead of enumerating misreads.
GAP = r'[^0-9가-힣]+'
# Separate captures for times keep ICU and Python replacements identical.
# NOISE is non-capturing, so the $1..$9 replacement numbering below is unchanged.
ROW = HEADER + NOISE + STATION + GAP + STATION + r'\s+' + TIME + GAP + TIME + r'(?![0-9:])'
COLUMN = HEADER + NOISE + STATION + r'\s+' + TIME + GAP + STATION + r'\s+' + TIME + r'(?![0-9:])'
REPLACEMENTS = [(ROW, '⟦$1-$2-$3 | $4 → $5 | $6:$7–$8:$9⟧'),
                (COLUMN, '⟦$1-$2-$3 | $4 → $7 | $5:$6–$8:$9⟧')]
CANONICAL = r'⟦(20[0-9]{2}-[0-9]{2}-[0-9]{2}) \| ([가-힣]{1,12}) → ([가-힣]{1,12}) \| ([0-9]{2}:[0-9]{2})–([0-9]{2}:[0-9]{2})⟧'
KST = timezone(timedelta(hours=9))

def normalized(text):
    text = text.replace('：', ':')
    text = re.sub(r'(?<=[0-9])\s*:\s*(?=[0-9])', ':', text)
    for pattern, replacement in REPLACEMENTS:
        replacement = re.sub(r'\$(\d+)', lambda m: r'\g<' + m[1] + '>', replacement)
        text = re.sub(pattern, replacement, text)
    return text

def parse(text):
    events, seen = [], set()
    for m in re.finditer(CANONICAL, normalized(text)):
        day, origin, destination, start, end = m.groups()
        try:
            begin = datetime.fromisoformat(day + 'T' + start).replace(tzinfo=KST)
            finish = datetime.fromisoformat(day + 'T' + end).replace(tzinfo=KST)
        except ValueError:
            continue
        # This first version deliberately rejects ambiguous overnight journeys.
        if finish <= begin or origin == destination:
            continue
        key = f'rail-calendar:v1:{day}:{origin}:{destination}:{start}:{end}'
        if key in seen:
            continue
        seen.add(key)
        events.append(dict(title=f'열차 {origin} → {destination}', start=begin.isoformat(),
                           end=finish.isoformat(), key=key, label=m[0]))
    return events
