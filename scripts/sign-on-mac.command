#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
if [[ "$(uname -s)" != Darwin ]] || ! command -v shortcuts >/dev/null 2>&1; then
  print -u2 '이 단계에는 단축어 앱이 설치된 Mac이 필요합니다.'
  exit 1
fi
# Apple validates a copy of the shortcut during signing. No ticket images are included.
shortcuts sign --mode anyone \
  --input "$PROJECT_DIR/dist/승차권-캘린더.unsigned.shortcut" \
  --output "$PROJECT_DIR/dist/승차권-캘린더.shortcut"
print '서명 완료. 아이폰으로 dist/승차권-캘린더.shortcut 파일을 전달해 설치하세요.'
open -R "$PROJECT_DIR/dist/승차권-캘린더.shortcut"
