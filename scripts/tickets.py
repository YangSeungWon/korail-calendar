"""Shared OCR patterns. No OCR/network/calendar access in this reference parser.

A ticket card puts the origin and departure time on the left of the screen and the
destination and arrival time on the right. Apple Vision does not read a screenshot card by
card: on the device it returned every card's left column first and every card's right column
afterwards, so a card's arrival time was separated from its header by two other cards. Rather
than depend on that ordering, the shortcut crops the screenshot down the middle and reads each
half on its own. Each half is a single narrow column, so it is read top to bottom, and the Nth
departure lines up with the Nth arrival.
"""
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
# Filter chips and tab-bar labels land between a card header and its station. Skipping
# digit-free lines only is what keeps this from reaching into the next card: every date and
# time line carries digits.
NOISE = r'(?:[^\n0-9]*\n)*?'
# Left half: date, '기차 승차권', origin, departure time. Right half: destination and arrival
# time. The right half is anchored on the '1매' of the same header row that anchors the left,
# so a card clipped by the screen edge drops out of both halves together instead of only one.
LEFT = HEADER + NOISE + STATION + r'\s+' + TIME + r'(?![0-9:])'
RIGHT = r'[0-9]+\s*매\s*' + NOISE + STATION + r'\s+' + TIME + r'(?![0-9:])'
# Separate captures for times keep ICU and Python replacements identical. The markers keep a
# replaced row distinguishable from ordinary text during the match that follows.
LEFT_REPLACEMENTS = [(LEFT, '⟦$1-$2-$3 | $4 | $5:$6⟧')]
RIGHT_REPLACEMENTS = [(RIGHT, '⟪$1 | $2:$3⟫')]
CANONICAL_LEFT = r'⟦(20[0-9]{2}-[0-9]{2}-[0-9]{2}) \| ([가-힣]{1,12}) \| ([0-9]{2}:[0-9]{2})⟧'
CANONICAL_RIGHT = r'⟪([가-힣]{1,12}) \| ([0-9]{2}:[0-9]{2})⟫'
# 'Get Group from Matched Text' returns nothing on the device at every index, so no field is
# ever read out of a match. Everything is derived with Replace Text instead, whose $1 numbering
# does work there. These strip the markers so the two halves can simply be concatenated.
DEPARTURE_PLAIN = (CANONICAL_LEFT, '$1 $2 $3')
ARRIVAL_PLAIN = (CANONICAL_RIGHT, '$1 $2')
# One candidate, as shown on the selection screen: '2030-09-23 서울 19:10 → 부산 21:50'.
CANDIDATE = (r'(20[0-9]{2}-[0-9]{2}-[0-9]{2}) ([가-힣]{1,12}) ([0-9]{2}:[0-9]{2})'
             r' → ([가-힣]{1,12}) ([0-9]{2}:[0-9]{2})')
# Every value the shortcut needs from a selected candidate, as a replacement of the whole line.
START_ISO = (CANDIDATE, '$1T$3:00+09:00')
END_ISO = (CANDIDATE, '$1T$5:00+09:00')
TITLE = (CANDIDATE, '열차 $2 → $4')
ORIGIN = (CANDIDATE, '$2')
DESTINATION = (CANDIDATE, '$4')
DEPARTURE_CLOCK = (CANDIDATE, '$3')
ARRIVAL_CLOCK = (CANDIDATE, '$5')
KEY = (CANDIDATE, 'rail-calendar:v1:$1:$2:$4:$3:$5')
KST = timezone(timedelta(hours=9))


def normalized(text, replacements):
    text = text.replace('：', ':')
    text = re.sub(r'(?<=[0-9])\s*:\s*(?=[0-9])', ':', text)
    for pattern, replacement in replacements:
        replacement = re.sub(r'\$(\d+)', lambda m: r'\g<' + m[1] + '>', replacement)
        text = re.sub(pattern, replacement, text)
    return text


def halves(left, right):
    """Departure and arrival rows, in card order, from the two cropped halves."""
    departures = re.findall(CANONICAL_LEFT, normalized(left, LEFT_REPLACEMENTS))
    arrivals = re.findall(CANONICAL_RIGHT, normalized(right, RIGHT_REPLACEMENTS))
    return departures, arrivals


def parse(left, right):
    departures, arrivals = halves(left, right)
    # Pairing is positional, so an unequal count means the halves disagree about how many
    # cards are on screen. Guessing would attach one card's arrival to another card, so
    # nothing is offered at all.
    if len(departures) != len(arrivals):
        return []
    events, seen = [], set()
    for (day, origin, start), (destination, end) in zip(departures, arrivals):
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
                           end=finish.isoformat(), key=key,
                           label=f'{day} {origin} {start} → {destination} {end}'))
    return events
