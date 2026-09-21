import json
import plistlib
import re
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tickets import parse, REPLACEMENTS, CANONICAL
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / 'fixtures/synthetic-cards.txt').read_text()


def card(day='2030.09.23', route='서울 부산\n19:10 21:50'):
    return f'{day} (Wed)\n2일 전\n기차 승차권\n1매\n{route}\n'


class TicketTests(unittest.TestCase):
    def test_visible_three(self):
        events = parse(SAMPLE)
        self.assertEqual(len(events), 3)
        self.assertEqual([e['start'] for e in events], [
            '2030-09-23T19:10:00+09:00', '2030-09-27T09:00:00+09:00', '2030-09-27T17:00:00+09:00'])
        self.assertEqual([e['end'] for e in events], [
            '2030-09-23T21:50:00+09:00', '2030-09-27T11:40:00+09:00', '2030-09-27T19:40:00+09:00'])

    def test_column_ocr(self):
        self.assertEqual(parse(card(route='서울\n19:10\n부산\n21:50')), parse(card()))

    def test_arrows_fullwidth_colons_spacing(self):
        self.assertEqual(parse(card(route='서울 → 부산\n19 ： 10 → 21 ： 50')), parse(card()))

    def test_five_cards_not_hardcoded(self):
        more = card('2030.09.28') + card('2030.09.29')
        self.assertEqual(len(parse(SAMPLE + more)), 5)

    def test_overlap_dedup_and_distinct_departures(self):
        self.assertEqual(len(parse(SAMPLE + SAMPLE)), 3)
        self.assertNotEqual(parse(SAMPLE)[1]['key'], parse(SAMPLE)[2]['key'])

    def test_partial_card_does_not_borrow_next_card(self):
        partial = card(route='서울 부산\n19:10')
        events = parse(partial + card('2030.09.27'))
        self.assertEqual(len(events), 1)
        self.assertIn('2030-09-27', events[0]['start'])

    def test_partial_without_date_is_ignored(self):
        self.assertEqual(parse('서울 부산\n19:10 21:50\n' + card()), parse(card()))

    def test_single_station_is_not_split_into_two(self):
        self.assertEqual(parse(card(route='서울\n19:10 21:50')), [])

    def test_invalid_times(self):
        for route in ['서울 부산\n25:42 21:50', '서울 부산\n20:69 21:50', '서울 부산\n19:10 21:509']:
            self.assertEqual(parse(card(route=route)), [])

    def test_invalid_dates_rejected_by_shared_regex(self):
        from tickets import normalized
        for day in ['2030.02.29', '2030.02.31', '2030.04.31', '2030.13.01']:
            self.assertIsNone(re.search(CANONICAL, normalized(card(day))))
        self.assertEqual(len(parse(card('2028.02.29'))), 1)

    def test_ambiguous_overnight_zero_duration_same_station_skipped(self):
        for route in ['서울 부산\n23:42 01:12', '서울 부산\n19:10 19:10', '서울 서울\n19:10 21:50']:
            self.assertEqual(parse(card(route=route)), [])

    def test_unrelated_text_no_ticket(self):
        self.assertEqual(parse('2030.09.23 회의 서울 부산 19:10 21:50'), [])


class ShortcutStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = plistlib.loads((ROOT / 'dist/승차권-캘린더.unsigned.shortcut').read_bytes())
        cls.actions = cls.flow['WFWorkflowActions']

    def test_binary_xml_and_json_agree(self):
        self.assertEqual(self.flow, plistlib.loads((ROOT / 'dist/승차권-캘린더.plist').read_bytes()))
        self.assertEqual(self.flow, json.loads((ROOT / 'dist/actions.json').read_text()))

    def test_shared_patterns_embedded(self):
        replacements = [a['WFWorkflowActionParameters'] for a in self.actions if a['WFWorkflowActionIdentifier'].endswith('text.replace')]
        for pattern, replacement in REPLACEMENTS:
            self.assertTrue(any(p['WFReplaceTextFind'] == pattern and p['WFReplaceTextReplace'] == replacement for p in replacements))

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
                        self.assertEqual(encoded[i*2:i*2+2].decode('utf-16-le'), '\ufffc')
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
            self.assertNotRegex(action['WFWorkflowActionIdentifier'], r'downloadurl|openurl|sendmessage|sendemail|delete|remove')

    def test_calendar_picker_and_persistent_duplicate_check(self):
        q = self.flow['WFWorkflowImportQuestions'][0]
        self.assertTrue(self.actions[q['ActionIndex']]['WFWorkflowActionIdentifier'].endswith('addnewevent'))
        finder = next(a for a in self.actions if a['WFWorkflowActionIdentifier'].endswith('filter.calendarevents'))
        predicates = finder['WFWorkflowActionParameters']['WFContentItemFilter']['Value']
        self.assertFalse(predicates['WFContentPredicateBoundedDate'])
        self.assertEqual(predicates['WFActionParameterFilterTemplates'][0]['Property'], 'Notes')

if __name__ == '__main__':
    unittest.main()
