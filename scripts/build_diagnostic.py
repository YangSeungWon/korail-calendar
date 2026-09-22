"""Throwaway probe: does 'Get Group from Matched Text' index the way this project assumes?

The candidate list used to be the matched strings themselves, so group extraction never ran on
a device. The cropped-halves build rebuilds each candidate out of capture groups, and on the
device the station names and arrival time came back empty -- so check what each index returns.
"""
import plistlib
import sys
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tickets import CANONICAL_LEFT

ROOT = Path(__file__).resolve().parents[1]
A = []

def uid(label):
    return str(uuid5(NAMESPACE_URL, 'rail-calendar/diag3/' + label)).upper()

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
            result += '￼'
        else:
            result += str(part)
    return {'Value': {'string': result, 'attachmentsByRange': attachments},
            'WFSerializationType': 'WFTextTokenString'}

def show(*parts):
    return action('showresult', Text=text(*parts))

sample = action('gettext', WFTextActionText=text('⟦2026-09-23 | 포항 | 20:42⟧'))
matched = action('text.match', text=text(sample), WFMatchTextPattern=CANONICAL_LEFT,
                 WFMatchTextCaseSensitive=True)
show('① 매칭된 문자열 ↓\n', matched, '\n\n비어 있으면 매칭 자체가 실패한 것입니다.')

def at(index):
    return action('text.match.getgroup', WFInput=token(matched),
                  WFGetGroupType='Group At Index', WFGroupIndex=index)

show('② 인덱스별 그룹\n\n0 → [', at(0), ']\n1 → [', at(1), ']\n2 → [', at(2), ']\n3 → [', at(3), ']')

# If 'Group At Index' is not the right selector, this is the other shape the action takes.
show('③ 전체 그룹 ↓\n', action('text.match.getgroup', WFInput=token(matched),
                             WFGetGroupType='All Groups'))

workflow = {
    'WFWorkflowName': '승차권 진단3', 'WFWorkflowActions': A,
    'WFWorkflowClientVersion': '4046.0.2.2', 'WFWorkflowMinimumClientVersion': 900,
    'WFWorkflowMinimumClientVersionString': '900',
    'WFWorkflowIcon': {'WFWorkflowIconStartColor': 4271458815, 'WFWorkflowIconGlyphNumber': 59511},
    'WFWorkflowTypes': ['ActionExtension'], 'WFWorkflowInputContentItemClasses': ['WFImageContentItem'],
    'WFWorkflowHasOutputFallback': False, 'WFWorkflowHasShortcutInputVariables': True,
}
(ROOT / 'dist/승차권-진단3.unsigned.shortcut').write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
print(f'Built group probe with {len(A)} actions.')
