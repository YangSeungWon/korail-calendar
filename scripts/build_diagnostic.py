"""Throwaway probe: verify the crop primitives on a real device before rewriting the shortcut.

iOS OCR groups the whole screen into vertical columns, so a card's arrival station and time
get separated from its header. Cropping the screenshot in half is meant to make the split
deterministic instead of depending on Vision's reading order. This probe only checks that the
image-detail and crop actions exist and accept the parameters used here.
"""
import plistlib
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
A = []

def uid(label):
    return str(uuid5(NAMESPACE_URL, 'rail-calendar/diag2/' + label)).upper()

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

shot = action('getlastscreenshot', WFGetLatestPhotoCount=1)

width = action('properties.images', WFInput=token(shot), WFContentItemPropertyName='Width')
height = action('properties.images', WFInput=token(shot), WFContentItemPropertyName='Height')
show('① 가로 ', width, ' / 세로 ', height, '\n둘 다 숫자로 보이면 이미지 정보 액션은 정상입니다.')

# Literal numbers go in as numbers; text() is for variable references only.
half = action('math', WFInput=token(width), WFMathOperation='÷', WFMathOperand=2)

left = action('image.crop', WFInput=token(shot), WFImageCropWidth=text(half),
              WFImageCropHeight=text(height), WFImageCropPosition='Top Left')
right = action('image.crop', WFInput=token(shot), WFImageCropWidth=text(half),
               WFImageCropHeight=text(height), WFImageCropPosition='Top Right')

show('② 왼쪽 절반 OCR ↓\n', action('extracttextfromimage', WFImage=token(left)))
show('③ 오른쪽 절반 OCR ↓\n', action('extracttextfromimage', WFImage=token(right)))

workflow = {
    'WFWorkflowName': '승차권 진단2', 'WFWorkflowActions': A,
    'WFWorkflowClientVersion': '4046.0.2.2', 'WFWorkflowMinimumClientVersion': 900,
    'WFWorkflowMinimumClientVersionString': '900',
    'WFWorkflowIcon': {'WFWorkflowIconStartColor': 4271458815, 'WFWorkflowIconGlyphNumber': 59511},
    'WFWorkflowTypes': ['ActionExtension'], 'WFWorkflowInputContentItemClasses': ['WFImageContentItem'],
    'WFWorkflowHasOutputFallback': False, 'WFWorkflowHasShortcutInputVariables': True,
}
(ROOT / 'dist/승차권-진단2.unsigned.shortcut').write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
print(f'Built crop probe with {len(A)} actions.')
