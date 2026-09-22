"""Build an UNSIGNED native Apple Shortcut. Requires Mac signing and device testing."""
import json
import plistlib
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
from tickets import (LEFT_REPLACEMENTS, RIGHT_REPLACEMENTS,
                     CANONICAL_LEFT, CANONICAL_RIGHT, CANONICAL)

ROOT = Path(__file__).resolve().parents[1]
# Serialised so the calendar row is explicit in the editor instead of silently
# falling back to the device default. Must match the calendar name on the device.
CALENDAR = '집'
A = []

def uid(label):
    return str(uuid5(NAMESPACE_URL, 'rail-calendar/v1/' + label)).upper()

def action(name, **parameters):
    identity = uid(str(len(A)) + '/' + name)
    parameters['UUID'] = identity
    A.append(dict(WFWorkflowActionIdentifier='is.workflow.actions.' + name,
                  WFWorkflowActionParameters=parameters))
    return {'Type': 'ActionOutput', 'OutputUUID': identity, 'OutputName': 'Result'}

def token(value):
    return {'Value': value, 'WFSerializationType': 'WFTextTokenAttachment'}

def text(*parts):
    result, attachments = '', {}
    for part in parts:
        if isinstance(part, dict):
            offset = len(result.encode('utf-16-le')) // 2
            attachments[f'{{{offset}, 1}}'] = part
            result += '\ufffc'
        else:
            result += str(part)
    return {'Value': {'string': result, 'attachmentsByRange': attachments},
            'WFSerializationType': 'WFTextTokenString'}

def begin_if(value, code, **kwargs):
    group = uid('if/' + str(len(A)))
    action('conditional', GroupingIdentifier=group, WFControlFlowMode=0,
           WFInput={'Type': 'Variable', 'Variable': token(value)}, WFCondition=code, **kwargs)
    return group

def otherwise(group):
    action('conditional', GroupingIdentifier=group, WFControlFlowMode=1)

def end_if(group):
    return action('conditional', GroupingIdentifier=group, WFControlFlowMode=2)

def replace(value, pattern, replacement):
    return action('text.replace', WFInput=text(value), WFReplaceTextFind=pattern,
                  WFReplaceTextReplace=replacement, WFReplaceTextRegularExpression=True,
                  WFReplaceTextCaseSensitive=True)

def match(value, pattern):
    return action('text.match', text=text(value), WFMatchTextPattern=pattern,
                  WFMatchTextCaseSensitive=True)

def group(value, index):
    return action('text.match.getgroup', WFInput=token(value), WFGetGroupType='Group At Index', WFGroupIndex=index)

def literal(*parts):
    return action('gettext', WFTextActionText=text(*parts))

def warn(message):
    return action('showresult', Text=text(message))

def setvar(name, value):
    return action('setvariable', WFVariableName=name, WFInput=token(value))

def var(name):
    return {'Type': 'Variable', 'VariableName': name}

def increment(name):
    n = action('math', WFInput=token(var(name)), WFMathOperation='+', WFMathOperand=1)
    setvar(name, n)

def loop(value):
    g = uid('loop/' + str(len(A)))
    a = action('repeat.each', GroupingIdentifier=g, WFControlFlowMode=0, WFInput=token(value))
    a['OutputName'] = 'Repeat Item'
    return g, a

def end_loop(g):
    return action('repeat.each', GroupingIdentifier=g, WFControlFlowMode=2)

action('comment', WFCommentActionText='승차권 → 캘린더 (기기 검증 전 초안)\n공유한 이미지, 또는 입력이 없으면 가장 최근 스크린샷에서 완전히 보이는 승차권을 처리합니다. 뒷면 탭으로 쓸 때는 먼저 스크린샷을 찍으세요. 아래로 스크롤한 후 다시 실행하세요. 이미 등록한 일정은 메모의 식별자로 확인합니다. 취소·변경은 자동 반영하지 않습니다.')
input_value = {'Type': 'ExtensionInput'}
branch = begin_if(input_value, 100)
setvar('승차권 이미지', input_value)
otherwise(branch)
# iOS Shortcuts cannot capture the screen itself; 'Take Screenshot' is a macOS-only action.
# Back Tap therefore reads the screenshot the user has just taken with the system gesture.
screenshot = action('getlastscreenshot', WFGetLatestPhotoCount=1)
setvar('승차권 이미지', screenshot)
end_if(branch)
# Multiple share-sheet screenshots can be processed together; no card spans images.
empty = action('nothing')
setvar('후보', empty)
images_loop, image_item = loop(var('승차권 이미지'))
# Vision reads the whole screen in columns, so a card's arrival time can come back separated
# from its header by other cards. Cropping down the middle makes each half a single narrow
# column that is read top to bottom, which is what lets departures and arrivals be paired by
# position instead of by proximity in the text.
width = action('properties.images', WFInput=token(image_item), WFContentItemPropertyName='Width')
height = action('properties.images', WFInput=token(image_item), WFContentItemPropertyName='Height')
half = action('math', WFInput=token(width), WFMathOperation='÷', WFMathOperand=2)

def read_half(position, replacements, canonical):
    cropped = action('image.crop', WFInput=token(image_item), WFImageCropWidth=text(half),
                     WFImageCropHeight=text(height), WFImageCropPosition=position)
    clean = action('extracttextfromimage', WFImage=token(cropped))
    clean = replace(clean, '：', ':')
    clean = replace(clean, r'(?<=[0-9])\s*:\s*(?=[0-9])', ':')
    for pattern, replacement in replacements:
        clean = replace(clean, pattern, replacement)
    return match(clean, canonical)

departures = read_half('Top Left', LEFT_REPLACEMENTS, CANONICAL_LEFT)
arrivals = read_half('Top Right', RIGHT_REPLACEMENTS, CANONICAL_RIGHT)
# Pairing is positional, so unequal counts mean the halves disagree about how many cards are
# on screen -- a card clipped by the screen edge, say. Attaching one card's arrival to another
# card would create a plausible-looking wrong event, so this offers nothing instead.
gap = action('math', WFInput=token(action('count', Input=token(departures), WFCountType='Items')),
             WFMathOperation='-', WFMathOperand=text(action('count', Input=token(arrivals), WFCountType='Items')))
paired = begin_if(gap, 4, WFNumberValue='0')
setvar('색인', action('number', WFNumberActionNumber=1))
pair_loop, departure = loop(departures)
arrival = action('getitemfromlist', WFInput=token(arrivals), WFItemSpecifier='Item At Index',
                 WFItemIndex=text(var('색인')))
left = match(departure, CANONICAL_LEFT)
day, origin, start = [group(left, i) for i in range(1, 4)]
right = match(arrival, CANONICAL_RIGHT)
destination, end = [group(right, i) for i in range(1, 3)]
action('appendvariable', WFVariableName='후보', WFInput=token(
    literal('⟦', day, ' | ', origin, ' → ', destination, ' | ', start, '–', end, '⟧')))
increment('색인')
end_loop(pair_loop)
otherwise(paired)
warn('카드를 온전히 읽지 못했습니다. 출발 정보와 도착 정보의 개수가 맞지 않습니다. 잘못 짝지어진 일정을 만들지 않으려고 등록을 건너뜁니다. 카드 전체가 화면 안에 들어오도록 조정한 뒤 다시 실행하세요.')
end_if(paired)
end_loop(images_loop)
none = begin_if(var('후보'), 101)
warn('완전히 보이는 승차권을 찾지 못했습니다. 뒷면 탭으로 실행했다면 먼저 승차권 목록을 스크린샷으로 찍었는지 확인하세요. 날짜·출발역·도착역·두 시간이 모두 보이게 스크롤한 뒤 다시 실행하세요. 상세 화면은 아직 지원하지 않습니다.')
action('exit')
end_if(none)
selected = action('choosefromlist', WFInput=token(var('후보')),
                  WFChooseFromListActionPrompt='날짜·역·시간을 확인하고 등록할 승차권을 선택하세요. 중복은 건너뜁니다.',
                  WFChooseFromListActionSelectMultiple=True, WFChooseFromListActionSelectAll=True)
zero = action('number', WFNumberActionNumber=0)
setvar('추가 수', zero)
setvar('중복 수', zero)
setvar('건너뜀 수', zero)

selected_loop, item = loop(selected)
parsed = match(item, CANONICAL)
day, origin, destination, start, end = [group(parsed, i) for i in range(1, 6)]
start_iso = literal(day, 'T', start, ':00+09:00')
end_iso = literal(day, 'T', end, ':00+09:00')
start_date = action('date', WFDateActionMode='Specified Date', WFDateActionDate=text(start_iso))
end_date = action('date', WFDateActionMode='Specified Date', WFDateActionDate=text(end_iso))
# Numeric clock comparison avoids locale-dependent date condition serialization.
start_num = replace(start, ':', '')
end_num = replace(end, ':', '')
difference = action('math', WFInput=token(end_num), WFMathOperation='-', WFMathOperand=text(start_num))
valid = begin_if(difference, 2, WFNumberValue='0')
same_station = begin_if(origin, 5, WFConditionalActionString=text(destination))
key = literal('rail-calendar:v1:', day, ':', origin, ':', destination, ':', start, ':', end)
found = action('filter.calendarevents', WFContentItemFilter={
    'Value': {'WFActionParameterFilterPrefix': 1, 'WFContentPredicateBoundedDate': False,
              'WFActionParameterFilterTemplates': [
                  {'Property': 'Notes', 'Operator': 99, 'Removable': True,
                   'Values': {'String': text(key), 'Unit': 4}}]},
    'WFSerializationType': 'WFContentPredicateTableTemplate'}, WFContentItemLimitEnabled=True,
    WFContentItemLimitNumber=1)
missing = begin_if(found, 101)
new_event_index = len(A)
created = action('addnewevent', WFCalendarItemCalendar=CALENDAR,
    WFCalendarItemTitle=text('열차 ', origin, ' → ', destination),
    WFCalendarItemLocation=text(origin), WFCalendarItemDates=True,
    WFCalendarItemStartDate=text(start_date), WFCalendarItemEndDate=text(end_date),
    WFCalendarItemAllDay=False, WFCalendarItemNotes=text(key, '\n승차권 화면에서 등록. 변경·취소 시 직접 수정하세요.'),
    WFAlertTime='30 minutes before', WFCalendarItemShowComposeSheet=False)
increment('추가 수')
otherwise(missing)
increment('중복 수')
end_if(missing)
otherwise(same_station)
increment('건너뜀 수')
end_if(same_station)
otherwise(valid)
increment('건너뜀 수')
end_if(valid)
end_loop(selected_loop)
summary = literal('추가 ', var('추가 수'), '개 · 중복 ', var('중복 수'), '개 · 시간/구간 확인 필요 ', var('건너뜀 수'), '개\n날짜나 시간이 잘린 카드는 후보에 포함되지 않습니다. 아래 승차권은 스크롤 후 다시 실행하세요.')
action('showresult', Text=text(summary))
workflow = {
    'WFWorkflowName': '승차권 캘린더', 'WFWorkflowActions': A,
    'WFWorkflowClientVersion': '4046.0.2.2', 'WFWorkflowMinimumClientVersion': 900,
    'WFWorkflowMinimumClientVersionString': '900',
    'WFWorkflowIcon': {'WFWorkflowIconStartColor': 4282601983, 'WFWorkflowIconGlyphNumber': 59771},
    'WFWorkflowTypes': ['ActionExtension'], 'WFWorkflowInputContentItemClasses': ['WFImageContentItem'],
    'WFWorkflowHasOutputFallback': False, 'WFWorkflowHasShortcutInputVariables': True,
    'WFWorkflowImportQuestions': [{'ActionIndex': new_event_index, 'Category': 'Parameter',
        'ParameterKey': 'WFCalendarItemCalendar', 'Text': '승차권을 저장할 캘린더를 선택하세요.'}],
}
(ROOT / 'dist').mkdir(exist_ok=True)
(ROOT / 'dist/승차권-캘린더.unsigned.shortcut').write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
(ROOT / 'dist/승차권-캘린더.plist').write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_XML))
(ROOT / 'dist/actions.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2))
print(f'Built unsigned shortcut with {len(A)} actions. Mac signing and iPhone validation remain required.')
