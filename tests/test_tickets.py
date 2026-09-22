import json
import plistlib
import re
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tickets import (parse, normalized, halves, LEFT_REPLACEMENTS, RIGHT_REPLACEMENTS,
                     CANONICAL_LEFT, CANONICAL_RIGHT)
ROOT = Path(__file__).resolve().parents[1]
LEFT_SAMPLE = (ROOT / 'fixtures/synthetic-left.txt').read_text()
RIGHT_SAMPLE = (ROOT / 'fixtures/synthetic-right.txt').read_text()


def card(day='2030.09.23', origin='서울', destination='부산', start='19:10', end='21:50'):
    """One card as the two cropped halves see it: origin left, destination right."""
    return (f'{day} (Wed)\n기차 승차권\n{origin}\n{start}\n',
            f'내일\n1매\n{destination}\n{end}\n')


def joined(*cards):
    return ''.join(c[0] for c in cards), ''.join(c[1] for c in cards)


class TicketTests(unittest.TestCase):
    def test_visible_three(self):
        events = parse(LEFT_SAMPLE, RIGHT_SAMPLE)
        self.assertEqual(len(events), 3)
        self.assertEqual([e['start'] for e in events], [
            '2030-09-23T19:10:00+09:00', '2030-09-27T09:00:00+09:00', '2030-09-27T17:00:00+09:00'])
        self.assertEqual([e['end'] for e in events], [
            '2030-09-23T21:50:00+09:00', '2030-09-27T11:40:00+09:00', '2030-09-27T19:40:00+09:00'])

    def test_arrivals_pair_by_position_not_proximity(self):
        """The right half carries no dates, so only order can connect it to the left half."""
        left, right = joined(card(), card('2030.09.27', '부산', '서울', '09:00', '11:40'))
        events = parse(left, right)
        self.assertEqual([e['title'] for e in events], ['🚅 서울 → 부산', '🚅 부산 → 서울'])

    def test_chips_between_header_and_station_are_skipped(self):
        left, right = card()
        self.assertEqual(parse(left.replace('기차 승차권\n', '기차 승차권\n이용권\n정기권\n'), right),
                         parse(left, right))

    def test_fullwidth_colons_and_spacing(self):
        left, right = card()
        self.assertEqual(parse(left.replace('19:10', '19 ： 10'), right.replace('21:50', '21 ： 50')),
                         parse(left, right))

    def test_clipped_header_row_drops_only_that_card(self):
        """Scrolling clips the blue header row, which both halves anchor on."""
        left, right = joined(card(), card('2030.09.27', '부산', '서울', '09:00', '11:40'))
        clipped = parse(left.replace('2030.09.23 (Wed)\n', ''), right.replace('내일\n', '', 1))
        self.assertEqual([e['title'] for e in clipped], ['🚅 부산 → 서울'])

    def test_unequal_halves_offer_nothing(self):
        left, _ = joined(card(), card('2030.09.27'))
        _, right = card()
        self.assertEqual(parse(left, right), [])

    def test_station_only_taken_when_a_time_follows(self):
        """'1매' and chip labels sit next to the destination and must not be read as stations."""
        _, right = card()
        self.assertEqual(re.findall(CANONICAL_RIGHT, normalized(right, RIGHT_REPLACEMENTS)),
                         [('부산', '21:50')])

    def test_card_without_a_departure_time_is_not_matched(self):
        left, right = card()
        departures, _ = halves(left.replace('19:10', ''), right)
        self.assertEqual(departures, [])

    def test_left_half_never_borrows_the_next_cards_station(self):
        left, _ = joined(card(start=''), card('2030.09.27', '부산'))
        departures = re.findall(CANONICAL_LEFT, normalized(left, LEFT_REPLACEMENTS))
        self.assertEqual([d[0] for d in departures], ['2030-09-27'])

    def test_dedup_and_distinct_departures(self):
        left, right = joined(card(), card())
        self.assertEqual(len(parse(left, right)), 1)
        events = parse(LEFT_SAMPLE, RIGHT_SAMPLE)
        self.assertNotEqual(events[1]['key'], events[2]['key'])

    def test_invalid_times(self):
        for start, end in [('25:42', '21:50'), ('20:69', '21:50')]:
            left, right = card(start=start, end=end)
            self.assertEqual(parse(left, right), [])

    def test_invalid_dates_rejected_by_shared_regex(self):
        for day in ['2030.02.29', '2030.02.31', '2030.04.31', '2030.13.01']:
            left, _ = card(day)
            self.assertIsNone(re.search(CANONICAL_LEFT, normalized(left, LEFT_REPLACEMENTS)))
        self.assertEqual(len(parse(*card('2028.02.29'))), 1)

    def test_ambiguous_overnight_zero_duration_same_station_skipped(self):
        for origin, destination, start, end in [('서울', '부산', '23:42', '01:12'),
                                                ('서울', '부산', '19:10', '19:10'),
                                                ('서울', '서울', '19:10', '21:50')]:
            self.assertEqual(parse(*card(origin=origin, destination=destination,
                                         start=start, end=end)), [])

    def test_unrelated_text_no_ticket(self):
        self.assertEqual(parse('2030.09.23 회의 서울 19:10', '부산 21:50'), [])


class ShortcutStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = plistlib.loads((ROOT / 'dist/승차권-캘린더.unsigned.shortcut').read_bytes())
        cls.actions = cls.flow['WFWorkflowActions']

    def test_binary_xml_and_json_agree(self):
        self.assertEqual(self.flow, plistlib.loads((ROOT / 'dist/승차권-캘린더.plist').read_bytes()))
        self.assertEqual(self.flow, json.loads((ROOT / 'dist/actions.json').read_text()))

    def test_shared_patterns_embedded(self):
        replacements = [a['WFWorkflowActionParameters'] for a in self.actions
                        if a['WFWorkflowActionIdentifier'].endswith('text.replace')]
        for pattern, replacement in LEFT_REPLACEMENTS + RIGHT_REPLACEMENTS:
            self.assertTrue(any(p['WFReplaceTextFind'] == pattern
                                and p['WFReplaceTextReplace'] == replacement for p in replacements))

    def test_both_halves_are_cropped_and_read(self):
        crops = [a['WFWorkflowActionParameters'] for a in self.actions
                 if a['WFWorkflowActionIdentifier'].endswith('image.crop')]
        self.assertEqual(sorted(c['WFImageCropPosition'] for c in crops), ['Top Left', 'Top Right'])
        self.assertEqual(sum(a['WFWorkflowActionIdentifier'].endswith('extracttextfromimage')
                             for a in self.actions), 2)

    def test_unequal_halves_guarded_before_pairing(self):
        """Without this the Nth departure could be paired with an unrelated arrival."""
        identifiers = [a['WFWorkflowActionIdentifier'] for a in self.actions]
        counts = [i for i, name in enumerate(identifiers) if name.endswith('.count')]
        self.assertEqual(len(counts), 2)
        guard = next(i for i, a in enumerate(self.actions)
                     if a['WFWorkflowActionParameters'].get('WFCondition') == 4)
        lookup = next(i for i, name in enumerate(identifiers) if name.endswith('getitemfromlist'))
        self.assertLess(max(counts), guard)
        self.assertLess(guard, lookup)

    def test_no_capture_group_extraction(self):
        """The group action returns nothing on the device; every field comes from Replace Text."""
        for action in self.actions:
            self.assertNotIn('getgroup', action['WFWorkflowActionIdentifier'])

    def test_every_event_field_is_derived_from_the_candidate(self):
        from tickets import START_ISO, END_ISO, TITLE, ORIGIN, DESTINATION, KEY
        replacements = [(a['WFWorkflowActionParameters'].get('WFReplaceTextFind'),
                         a['WFWorkflowActionParameters'].get('WFReplaceTextReplace'))
                        for a in self.actions
                        if a['WFWorkflowActionIdentifier'].endswith('text.replace')]
        for derived in (START_ISO, END_ISO, TITLE, ORIGIN, DESTINATION, KEY):
            self.assertIn(derived, replacements)

    def test_scopes_references_and_token_offsets(self):
        seen, stack = set(), []
        def visit(obj):
            if isinstance(obj, dict):
                if 'OutputUUID' in obj:
                    self.assertIn(obj['OutputUUID'], seen)
                if 'attachmentsByRange' in obj:
                    encoded = obj['string'].encode('utf-16-le')
                    for position in obj['attachmentsByRange']:
                        i = int(re.match(r'\{(\d+), 1\}', position)[1])
                        self.assertEqual(encoded[i*2:i*2+2].decode('utf-16-le'), '￼')
                for v in obj.values(): visit(v)
            elif isinstance(obj, list):
                for v in obj: visit(v)
        for action in self.actions:
            p = action['WFWorkflowActionParameters']
            visit(p)
            self.assertNotIn(p['UUID'], seen)
            seen.add(p['UUID'])
            if 'WFControlFlowMode' in p:
                mode, group = p['WFControlFlowMode'], p['GroupingIdentifier']
                if mode == 0: stack.append(group)
                elif mode == 1: self.assertEqual(stack[-1], group)
                elif mode == 2: self.assertEqual(stack.pop(), group)
        self.assertEqual(stack, [])

    def test_no_external_service_actions(self):
        for action in self.actions:
            self.assertNotRegex(action['WFWorkflowActionIdentifier'],
                                r'downloadurl|openurl|sendmessage|sendemail|delete|remove')

    def test_calendar_picker_and_persistent_duplicate_check(self):
        q = self.flow['WFWorkflowImportQuestions'][0]
        self.assertTrue(self.actions[q['ActionIndex']]['WFWorkflowActionIdentifier'].endswith('addnewevent'))
        self.assertIn('WFCalendarItemCalendar',
                      self.actions[q['ActionIndex']]['WFWorkflowActionParameters'])
        finder = next(a for a in self.actions if a['WFWorkflowActionIdentifier'].endswith('filter.calendarevents'))
        predicates = finder['WFWorkflowActionParameters']['WFContentItemFilter']['Value']
        self.assertFalse(predicates['WFContentPredicateBoundedDate'])
        self.assertEqual(predicates['WFActionParameterFilterTemplates'][0]['Property'], 'Notes')

if __name__ == '__main__':
    unittest.main()
