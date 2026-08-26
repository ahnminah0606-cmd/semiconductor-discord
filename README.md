# Semiconductor News Discord Crawler

반도체 관련 뉴스를 자동으로 수집하고, 정해진 시간마다 Discord 채널로 전송하는 크롤러 프로젝트입니다.

로컬에서는 `crontab`으로 자동 실행할 수 있고, GitHub Actions를 사용하면 맥북이 꺼져 있어도 클라우드에서 자동으로 실행할 수 있습니다.

## 주요 기능

* 반도체 뉴스 자동 크롤링
* NaverNews, TrendForce, SemiAnalysis에서 사이트별 최신 기사 5개 수집
* Playwright와 requests를 사이트 특성에 맞게 사용
* 기사 본문 수집 후 OpenAI API로 한국어 핵심 요약 생성
* 사이트별 최신 기사 5개를 하나의 Discord 묶음 메시지로 전송
* Discord 2,000자 제한을 넘으면 사이트 메시지를 안전하게 분할
* 본문 접근 실패 시 JSON-LD, 메타 description, 제목 순 fallback
* 전송 성공 URL을 기록해 같은 기사 재전송 방지
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
매일 오전 7시 7분 KST
      ↓
Python 크롤러 실행
      ↓
반도체 뉴스 수집
      ↓
기사 본문·메타 정보 추출
      ↓
OpenAI API 한국어 요약
      ↓
사이트별 메시지 구성
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
requests>=2.32.3,<3
beautifulsoup4==4.12.3
python-dotenv==1.0.1
lxml==5.2.2
openai>=1.40.0,<3
trafilatura>=1.12.0,<3
```

Playwright 브라우저도 설치합니다.

```bash
playwright install chromium
```

## 환경변수 설정

프로젝트 최상위에 `.env` 파일을 생성합니다.

```env
DISCORD_WEBHOOK_NAVER=https://discord.com/api/webhooks/... # NaverNews 채널
DISCORD_WEBHOOK_TRENDFORCE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SEMIANALYSIS=https://discord.com/api/webhooks/...
OPENAI_API_KEY=sk-...
# 선택 사항 (기본값: gpt-5-mini)
OPENAI_MODEL=gpt-5-mini
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

로컬에서 매일 오전 7시 7분에 실행하려면:

```bash
crontab -e
```

예시:

```cron
7 7 * * * cd "/Users/username/path/semiconductor_discord" && "/Users/username/path/semiconductor_discord/.venv/bin/python" semiconductor_news_crawler.py >> cron.log 2>&1
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
    - cron: "7 22 * * *"
  workflow_dispatch:
```

GitHub Actions의 cron은 UTC 기준이므로:

```text
UTC 22:07
=
KST 오전 07:07
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

다음 Repository secrets 4개를 등록합니다.

```text
DISCORD_WEBHOOK_NAVER
DISCORD_WEBHOOK_TRENDFORCE
DISCORD_WEBHOOK_SEMIANALYSIS
OPENAI_API_KEY
```

모델을 바꾸려면 `Settings → Secrets and variables → Actions → Variables`에서
선택적으로 `OPENAI_MODEL`을 등록합니다. 등록하지 않으면 `gpt-5-mini`를 사용합니다.

중복 방지 상태는 `data/sent_urls.json`에 저장되고 GitHub Actions가 실행 결과와
함께 저장소에 커밋합니다. Discord 전송에 실패한 기사는 상태에 기록하지 않아
다음 실행에서 다시 시도합니다.

워크플로우에서는 다음과 같이 사용합니다.

```yaml
env:
  DISCORD_WEBHOOK_NAVER: ${{ secrets.DISCORD_WEBHOOK_NAVER }}
  DISCORD_WEBHOOK_TRENDFORCE: ${{ secrets.DISCORD_WEBHOOK_TRENDFORCE }}
  DISCORD_WEBHOOK_SEMIANALYSIS: ${{ secrets.DISCORD_WEBHOOK_SEMIANALYSIS }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  OPENAI_MODEL: ${{ vars.OPENAI_MODEL || 'gpt-5-mini' }}
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
매일 오전 7시 7분
        ↓
GitHub Actions 실행
        ↓
Python 환경 구성
        ↓
필요 라이브러리 설치
        ↓
Playwright Chromium 설치
        ↓
NaverNews·TrendForce·SemiAnalysis 최신 기사 수집
        ↓
기사 본문 또는 접근 가능한 설명 추출
        ↓
OpenAI API 한국어 요약
        ↓
사이트별 Discord 채널로 묶음 전송
```

## 트러블슈팅 기록

### Actions 화면에 `Node.js 20 is deprecated` 경고가 표시되는 경우

작업 자체는 성공해도 오래된 JavaScript Action이 Node.js 20을 사용하면 GitHub가
지원 종료 경고를 표시합니다. Node.js 24 런타임을 사용하는 `actions/checkout@v6`,
`actions/setup-python@v6`, `actions/github-script@v8`로 업데이트했습니다. 화면에
과거 커밋 번호가 보이는 이전 실행 기록의 경고는 그대로 남지만, 변경 후 새로
실행되는 워크플로우부터 적용됩니다.

### 새 API 키를 넣었는데도 `401 invalid_api_key`가 발생한 경우

로컬 셸에 이전 `OPENAI_API_KEY`가 남아 있으면 `python-dotenv`의 기본 동작상
셸 값이 프로젝트 `.env`보다 우선될 수 있습니다. 이 프로젝트는 로컬 실행 시
`load_dotenv(override=True)`를 사용해 프로젝트 `.env`의 최신 키를 우선하도록
수정했습니다. GitHub Actions에는 `.env`가 없으므로 Repository Secret이 그대로
사용됩니다.

API 키 자체가 폐기됐거나 잘못 복사된 경우에도 같은 401 오류가 발생합니다.
이때는 OpenAI Platform에서 새 Secret Key를 만든 뒤 `OPENAI_API_KEY` 값을 전체
교체해야 합니다. 키 원문은 로그, 코드, GitHub 커밋에 남기지 않습니다.

### LLM 요약 실패 후 제목만 Discord에 전송된 경우

초기 구현에서는 API 오류가 나면 제목이나 메타 description으로 fallback하여
Discord에 전송했습니다. 이 때문에 잘못된 API 키 테스트에서도 불완전한 메시지가
발송됐습니다. 현재는 사이트의 기사 중 하나라도 LLM 요약에 실패하면 해당 사이트
메시지 전체를 발송하지 않고, URL도 전송 완료 상태로 기록하지 않습니다. 다음
실행에서 같은 기사들을 다시 시도할 수 있습니다.

### `DISCORD_WEBHOOK_URL`의 용도가 불분명했던 경우

기존 일반 명칭은 실제로 NaverNews 채널의 웹훅이었습니다. 코드와 문서, Actions
설정을 모두 `DISCORD_WEBHOOK_NAVER`로 변경했습니다. GitHub Actions에서는 기존
Secret의 이름을 직접 변경할 수 없으므로 동일한 웹훅 값으로 새 Secret을 등록해야
합니다.

### 네이버 뉴스가 0건이고 전자신문으로 표시되던 경우

기존 코드에는 동적 수집 성공 시 전자신문을 사용하고 실패 시에만 오래된 네이버
선택자를 사용하는 혼합 구조가 있었습니다. 네이버 뉴스 페이지의 현재 반도체 섹션
주소와 `a.sa_text_title` 선택자를 사용하도록 변경했습니다. 수집된 네이버 기사
본문도 다른 사이트와 동일하게 요약 파이프라인을 거칩니다.

### Discord 메시지가 2,000자를 넘는 경우

Discord 일반 메시지 제한보다 여유 있는 1,900자를 내부 기준으로 사용합니다.
사이트별 기사 5건을 우선 한 메시지로 묶고, 제한을 넘을 때만 `(계속)` 메시지로
분할합니다. 원문 URL은 잘리지 않도록 보존합니다.

### 같은 기사가 다음 날 다시 전송되는 경우

성공적으로 전송된 URL은 `data/sent_urls.json`에 기록합니다. GitHub Actions가 이
파일을 실행 결과와 함께 커밋하므로 다음 예약 실행에서도 중복을 확인할 수 있습니다.
로컬과 GitHub Actions를 동시에 실행하면 상태 커밋 시점에 따라 중복될 수 있으므로
주 자동화 방식 하나만 사용하는 것이 좋습니다.

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
