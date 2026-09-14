# 🌐 W.B.C 스크린야구: 24시간 무료 클라우드 배포 및 운영 매뉴얼

본 문서는 로컬 컴퓨터가 꺼져 있어도 회원들이 스마트폰(LTE/5G)이나 PC에서 24시간 언제든 접속하고, 운영진이 경기 기록을 입력/수정할 수 있도록 **무료 클라우드에 배포하는 전체 절차**를 안내합니다.

---

## 🎯 추천 배포 옵션: PythonAnywhere (가장 안정적 & 추천 ⭐⭐⭐)

파이썬(Flask)과 SQLite 데이터베이스에 최적화된 호스팅 서비스입니다.
- **비용**: 100% 무료
- **DB 유지**: SQLite 파일(`wbc_data.db`)이 재부팅되어도 지워지지 않고 영구 보존됨
- **도메인**: `https://<내아이디>.pythonanywhere.com` 무료 제공

### 1단계: PythonAnywhere 무료 회원가입
1. [https://www.pythonanywhere.com](https://www.pythonanywhere.com) 접속
2. 우측 상단 **Pricing & signup** 클릭
3. **Create a Beginner account (무료)** 선택
4. `Username`, `Email`, `Password` 입력 후 가입 완료
   *(주의: Username이 사이트 주소가 됩니다. 예: `wbcworld`로 가입 시 `https://wbcworld.pythonanywhere.com`)*

---

### 2단계: Git 저장소 복제 (1회만 진행)
1. PythonAnywhere 대시보드 상단 **Consoles** 메뉴 클릭
2. **Bash** 콘솔 클릭하여 터미널 창 진입
3. 아래 명령어를 차례대로 입력:

```bash
# 1. 깃허브 저장소 복제
git clone https://github.com/Irum725/WBC.git

# 2. 프로젝트 폴더 진입
cd WBC

# 3. 필요한 패키지 설치
pip install --user -r requirements.txt
```

---

### 3단계: Web App 생성 및 WSGI 연결
1. 상단 메뉴에서 **Web** 탭 클릭
2. **Add a new web app** 파란색 버튼 클릭
3. 도메인 확인 후 `Next` 클릭
4. 프레임워크 선택: **Manual configuration** (중요!) 선택 후 **Python 3.10** 선택 및 `Next`
5. 웹 앱 생성 후 설정 페이지에서 아래 2가지 항목 입력:
   - **Source code**: `/home/<내아이디>/WBC`
   - **Working directory**: `/home/<내아이디>/WBC`
6. 설정 페이지 중간의 **Code** 섹션에서 **WSGI configuration file** 링크(예: `/var/www/<내아이디>_pythonanywhere_com_wsgi.py`) 클릭
7. 에디터에 적혀 있는 기존 내용을 전부 지우고, 아래 **4줄만 입력** 후 상단 **Save** 클릭:

```python
import sys
import os

path = '/home/<내아이디>/WBC'
if path not in sys.path:
    sys.path.append(path)

from wsgi import application
```
*(※ `<내아이디>` 부분은 본인의 PythonAnywhere 아이디로 입력)*

---

### 4단계: 배포 적용 및 모바일 접속
1. 상단 **Web** 탭으로 다시 이동
2. 페이지 상단의 초록색 **Reload <내아이디>.pythonanywhere.com** 버튼 클릭!
3. 브라우저나 스마트폰에서 `https://<내아이디>.pythonanywhere.com` 접속 확인! 🎉

---

## 🔐 운영진 비밀번호 설정 안내

- **기본 비밀번호**: `7500` (세계로교회 전화번호 뒷자리)
- **비밀번호 변경 방법**:
  - PythonAnywhere의 **Web** 탭 하단 `Environment variables`에 아래 설정 추가:
    - Name: `ADMIN_PASSWORD`
    - Value: `원하는비밀번호`
  - 또는 로컬에서 `app.py`의 `ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '7500')`의 기본값을 수정하여 git push 후 pull

---

## 🔄 추후 코드 업데이트(현행화) 방법

GitHub에 새로운 기능이 커밋되었을 때, 서버에 최신 코드를 반영하는 방법:
1. PythonAnywhere **Consoles** -> **Bash** 콘솔 열기
2. 아래 2개 명령어 실행:
```bash
cd ~/WBC
git pull origin main
```
3. **Web** 탭에서 **Reload** 버튼 클릭하면 10초 만에 최신 기능 반영 완료!

---

## ⚡ 대안: 지금 당장 내 PC로 1분 만에 스마트폰 테스트 (Cloudflare Tunnel)

호스팅 가입 없이 지금 바로 외부 인터넷 주소를 띄워보고 싶을 때:
1. [Cloudflare Tunnel 다운로드](https://github.com/cloudflare/cloudflared/releases/latest) 후 `cloudflared.exe` 준비
2. 터미널에서 다음 명령어 실행:
   ```cmd
   cloudflared tunnel --url http://localhost:5000
   ```
3. 화면에 출력되는 `https://xxxx.trycloudflare.com` 링크를 카톡으로 보내면 스마트폰에서 즉시 접속 가능!
