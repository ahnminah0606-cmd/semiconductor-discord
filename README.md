# Semiconductor News Discord Crawler

반도체 관련 뉴스를 자동으로 수집하고, 정해진 시간마다 Discord 채널로 전송하는 크롤러 프로젝트입니다.

로컬에서는 `crontab`으로 자동 실행할 수 있고, GitHub Actions를 사용하면 맥북이 꺼져 있어도 클라우드에서 자동으로 실행할 수 있습니다.

## 주요 기능

* 반도체 뉴스 자동 크롤링
* Playwright 기반 동적 페이지 수집
* requests 기반 정적 크롤링 fallback
* Discord Webhook 자동 알림
* `.env`를 이용한 Webhook URL 보안 관리
* GitHub Actions를 통한 클라우드 자동 실행
* 크롤링 결과 저장 및 로그 관리

## 프로젝트 구조

```text
semiconductor_discord/
├── .github/
│   └── workflows/
│       └── semiconductor_news_crawler.yml
├── .env
├── .gitignore
├── requirements.txt
└── semiconductor_news_crawler.py
```

`.env`와 `.venv`는 GitHub에 업로드하지 않습니다.

## 실행 구조

```text
GitHub Actions
      ↓
매일 오전 7시 KST
      ↓
Python 크롤러 실행
      ↓
반도체 뉴스 수집
      ↓
Discord Webhook
      ↓
Discord 채널 자동 전송
```

## 설치

Python 3.11 환경을 기준으로 작성했습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`

```text
playwright==1.44.0
requests==2.32.0
beautifulsoup4==4.12.3
python-dotenv==1.0.1
lxml==5.2.2
```

Playwright 브라우저도 설치합니다.

```bash
playwright install chromium
```

## 환경변수 설정

프로젝트 최상위에 `.env` 파일을 생성합니다.

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Webhook URL은 외부에 노출되면 안 되므로 GitHub에 업로드하지 않습니다.

`.gitignore`

```gitignore
.env
.venv/
logs/
data/
__pycache__/
*.pyc
```

## 로컬 실행

```bash
python semiconductor_news_crawler.py
```

정상적으로 실행되면 뉴스가 수집되고 Discord Webhook을 통해 메시지가 전송됩니다.

## macOS crontab 자동 실행

로컬에서 매일 오전 7시에 실행하려면:

```bash
crontab -e
```

예시:

```cron
0 7 * * * cd "/Users/username/path/semiconductor_discord" && "/Users/username/path/semiconductor_discord/.venv/bin/python" semiconductor_news_crawler.py >> cron.log 2>&1
```

등록 확인:

```bash
crontab -l
```

단, 이 방식은 컴퓨터가 실행 가능한 상태여야 합니다.

## GitHub Actions 자동화

GitHub Actions를 사용하면 로컬 컴퓨터가 꺼져 있어도 자동으로 실행할 수 있습니다.

워크플로우 파일 위치:

```text
.github/workflows/semiconductor_news_crawler.yml
```

주요 설정:

```yaml
on:
  schedule:
    - cron: "0 22 * * *"
  workflow_dispatch:
```

GitHub Actions의 cron은 UTC 기준이므로:

```text
UTC 22:00
=
KST 오전 07:00
```

으로 설정했습니다.

## GitHub Secret 설정

Discord Webhook URL은 GitHub 저장소에 직접 작성하지 않고 GitHub Secrets에 저장합니다.

GitHub 저장소에서:

```text
Settings
→ Secrets and variables
→ Actions
→ New repository secret
```

다음과 같이 등록합니다.

```text
Name:
DISCORD_WEBHOOK_URL

Secret:
실제 Discord Webhook URL
```

워크플로우에서는 다음과 같이 사용합니다.

```yaml
env:
  DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
```

## GitHub Actions 환경

Playwright 1.44.0과의 호환성을 위해 Ubuntu 22.04 환경을 사용했습니다.

```yaml
runs-on: ubuntu-22.04
```

Playwright Chromium 설치:

```yaml
- name: Playwright Chromium 설치
  run: |
    playwright install --with-deps chromium
```

## GitHub 업로드

```bash
git add .
git commit -m "반도체 뉴스 Discord 크롤러 추가"
git push
```

`.env`가 GitHub에 올라가지 않는지 반드시 확인합니다.

```bash
git status
```

## 자동화 결과

최종적으로 다음 과정이 자동으로 수행됩니다.

```text
매일 오전 7시
        ↓
GitHub Actions 실행
        ↓
Python 환경 구성
        ↓
필요 라이브러리 설치
        ↓
Playwright Chromium 설치
        ↓
반도체 뉴스 크롤링
        ↓
Discord 채널로 자동 전송
```

## 주의사항

Discord Webhook URL은 비밀번호처럼 관리해야 합니다. `.env` 파일이나 GitHub 코드에 Webhook URL을 직접 올리지 않는 것이 중요합니다.

GitHub Actions와 로컬 `crontab`을 동시에 같은 시간에 실행하면 Discord에 같은 메시지가 중복 전송될 수 있습니다. GitHub Actions를 주 자동화 방식으로 사용할 경우 로컬 `crontab`은 제거하는 것이 좋습니다.

GitHub Actions의 예약 실행은 서버 상황에 따라 정확히 지정된 시각보다 몇 분 늦게 시작될 수 있습니다.

## 사용 기술

* Python 3.11
* Playwright
* Requests
* BeautifulSoup4
* python-dotenv
* lxml
* Discord Webhook
* GitHub Actions
* Git / GitHub
* crontab

