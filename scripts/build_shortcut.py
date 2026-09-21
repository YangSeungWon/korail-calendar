"""Build an UNSIGNED native Apple Shortcut. Requires Mac signing and device testing."""
import json
import plistlib
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
from tickets import REPLACEMENTS, CANONICAL

ROOT = Path(__file__).resolve().parents[1]
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

def loop(value):
    g = uid('loop/' + str(len(A)))
    a = action('repeat.each', GroupingIdentifier=g, WFControlFlowMode=0, WFInput=token(value))
    a['OutputName'] = 'Repeat Item'
    return g, a

def end_loop(g):
    return action('repeat.each', GroupingIdentifier=g, WFControlFlowMode=2)

action('comment', WFCommentActionText='승차권 → 캘린더 (기기 검증 전 초안)\n공유한 이미지 또는 현재 화면에서 완전히 보이는 승차권을 처리합니다. 아래로 스크롤한 후 다시 실행하세요. 이미 등록한 일정은 메모의 식별자로 확인합니다. 취소·변경은 자동 반영하지 않습니다.')
input_value = {'Type': 'ExtensionInput'}
branch = begin_if(input_value, 100)
setvar('승차권 이미지', input_value)
otherwise(branch)
screenshot = action('takescreenshot')
setvar('승차권 이미지', screenshot)
end_if(branch)
# Multiple share-sheet screenshots can be processed together; no card spans images.
empty = action('nothing')
setvar('후보', empty)
images_loop, image_item = loop(var('승차권 이미지'))
ocr = action('extracttextfromimage', WFImage=token(image_item))
clean = replace(ocr, '：', ':')
clean = replace(clean, r'(?<=[0-9])\s*:\s*(?=[0-9])', ':')
for pattern, replacement in REPLACEMENTS:
    clean = replace(clean, pattern, replacement)
candidates = match(clean, CANONICAL)
exists = begin_if(candidates, 100)
action('appendvariable', WFVariableName='후보', WFInput=token(candidates))
end_if(exists)
end_loop(images_loop)
none = begin_if(var('후보'), 101)
warn('완전히 보이는 승차권을 찾지 못했습니다. 날짜·출발역·도착역·두 시간이 모두 보이게 스크롤한 뒤 다시 실행하세요. 상세 화면은 아직 지원하지 않습니다.')
action('exit')
end_if(none)
selected = action('choosefromlist', WFInput=token(var('후보')),
                  WFChooseFromListActionPrompt='날짜·역·시간을 확인하고 등록할 승차권을 선택하세요. 중복은 건너뜁니다.',
                  WFChooseFromListActionSelectMultiple=True, WFChooseFromListActionSelectAll=True)
zero = action('number', WFNumberActionNumber=0)
setvar('추가 수', zero)
setvar('중복 수', zero)
setvar('건너뜀 수', zero)

def increment(name):
    n = action('math', WFInput=token(var(name)), WFMathOperation='+', WFMathOperand=1)
    setvar(name, n)

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
created = action('addnewevent', WFCalendarItemTitle=text('열차 ', origin, ' → ', destination),
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
