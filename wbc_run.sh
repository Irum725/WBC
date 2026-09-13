#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo ""
echo " ====================================================="
echo "  ⚾  W.B.C 스크린야구 기록 관리 시스템"
echo "  세계로교회 World Believers Club"
echo " ====================================================="
echo ""
if ! command -v python3 &> /dev/null; then
    echo " [오류] Python3가 없습니다. https://python.org 에서 설치하세요."
    read -p "Press any key..."; exit 1
fi
echo " [1/3] 패키지 설치 중..."
pip3 install -r requirements.txt -q
echo " [2/3] 서버 시작 중..."
( sleep 2 && { open "http://localhost:5000" 2>/dev/null || xdg-open "http://localhost:5000" 2>/dev/null; } ) &
echo " [3/3] 실행됩니다!"
echo ""
echo " ======================================"
echo "  👉 http://localhost:5000"
MY_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$MY_IP" ] && echo "  📱 http://$MY_IP:5000"
echo "  Ctrl+C 로 종료"
echo " ======================================"
echo ""
python3 app.py