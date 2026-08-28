"""반도체 뉴스 수집, 한국어 요약, Discord 일일 전송."""

import asyncio
import html
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

# 로컬 실행에서는 프로젝트 .env가 셸에 남은 오래된 값보다 우선한다.
# GitHub Actions에는 .env가 없으므로 Actions Secret에는 영향을 주지 않는다.
load_dotenv(override=True)
WEBHOOKS = {
    "naver": ("NaverNews", os.getenv("DISCORD_WEBHOOK_NAVER", "")),
    "trendforce": ("TrendForce", os.getenv("DISCORD_WEBHOOK_TRENDFORCE", "")),
    "semianalysis": ("SemiAnalysis", os.getenv("DISCORD_WEBHOOK_SEMIANALYSIS", "")),
}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
STATE_FILE = Path("data/sent_urls.json")
HEADERS = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/120 Safari/537.36"}
MAX_CANDIDATES = 20
MAX_SUMMARIES = 5

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"logs/crawler_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def item(source, title, url, description=""):
    return {"source": source, "title": " ".join(title.split()), "url": url,
            "description": " ".join(description.split()), "crawled_at": datetime.now().isoformat()}


def unique(items):
    return list({x["url"]: x for x in items if x.get("url")}.values())[:MAX_CANDIDATES]


def title_tokens(title):
    """제목 비교용 토큰 집합."""
    return {
        token.lower()
        for token in re.findall(r"[가-힣A-Za-z0-9]+", title)
        if len(token) >= 2
    }


def deduplicate_topics(articles, threshold=0.6):
    """언론사만 다른 동일 이슈를 제목 토큰 중복률로 제거한다."""
    kept = []
    kept_tokens = []
    for article in articles:
        tokens = title_tokens(article.get("title", ""))
        duplicate = False
        for previous in kept_tokens:
            smaller = min(len(tokens), len(previous))
            overlap = len(tokens & previous) / smaller if smaller else 0
            if overlap >= threshold:
                duplicate = True
                logger.info("유사 주제 제외: %s", article.get("title", ""))
                break
        if not duplicate:
            kept.append(article)
            kept_tokens.append(tokens)
    return kept


async def link_items(page, base, source, valid):
    found = []
    links = page.locator("a")
    for i in range(await links.count()):
        try:
            link = links.nth(i)
            title, href = (await link.inner_text()).strip(), await link.get_attribute("href")
            if title and len(title) >= 20 and href:
                url = urljoin(base, href)
                if valid(url):
                    found.append(item(source, title, url))
        except Exception:
            continue
    return unique(found)


async def crawl_links(context, source, url, valid):
    page = await context.new_page()
    try:
        logger.info("%s 크롤링 시작", source)
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)
        return await link_items(page, url, source, valid)
    except Exception as exc:
        logger.error("%s 크롤링 실패: %s", source, exc, exc_info=True)
        return []
    finally:
        await page.close()


async def crawl_naver():
    """네이버 IT/과학 > 반도체 최신 기사 후보를 수집한다."""
    url = "https://news.naver.com/main/list.naver?mode=LS2D&mid=shm&sid1=105&sid2=230"
    try:
        logger.info("NaverNews 크롤링 시작")
        response = await asyncio.to_thread(
            requests.get,
            url,
            headers={**HEADERS, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=20,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        found = []
        for link in soup.select("a.sa_text_title"):
            title, href = link.get_text(" ", strip=True), link.get("href", "")
            if title and href:
                found.append(item("NaverNews", title, urljoin(response.url, href)))
        return unique(found)
    except Exception as exc:
        logger.error("NaverNews 크롤링 실패: %s", exc, exc_info=True)
        return []


async def crawl_all():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        try:
            naver, tf, sa = await asyncio.gather(
                crawl_naver(),
                crawl_links(context, "TrendForce", "https://www.trendforce.com/news/category/semiconductors/",
                            lambda u: "trendforce.com/news/" in u and "/category/" not in u),
                crawl_links(context, "SemiAnalysis", "https://newsletter.semianalysis.com/archive",
                            lambda u: "semianalysis.com" in u and "/p/" in u),
            )
            return {"naver": naver, "trendforce": tf, "semianalysis": sa}
        finally:
            await browser.close()


def meta(soup, *selectors):
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            value = tag.get("content") or tag.get_text(" ", strip=True)
            if value:
                return " ".join(html.unescape(value).split())
    return ""


def json_ld_body(soup):
    def find(value):
        if isinstance(value, dict):
            if isinstance(value.get("articleBody"), str):
                return value["articleBody"]
            return next((result for child in value.values() if (result := find(child))), "")
        if isinstance(value, list):
            return next((result for child in value if (result := find(child))), "")
        return ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            if body := find(json.loads(script.string or "")):
                return " ".join(body.split())
        except (TypeError, json.JSONDecodeError):
            pass
    return ""


def fetch_article(article):
    """본문을 수집하고, 요약할 만큼 내용이 확보됐는지 표시한다."""
    try:
        response = requests.get(article["url"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        description = meta(soup, 'meta[property="og:description"]', 'meta[name="description"]',
                           'meta[name="twitter:description"]')
        body = trafilatura.extract(response.text, include_comments=False, include_tables=False,
                                   favor_precision=True) or json_ld_body(soup)
        article["description"] = description or article["description"]
        article["content"] = " ".join((body or description or "").split())[:12_000]
        article["content_ok"] = len(article["content"]) >= 200
        if article["content_ok"]:
            logger.info("본문 수집: %s (%d자)", article["url"], len(article["content"]))
        else:
            logger.warning("본문 부족으로 제외: %s (%d자)", article["url"], len(article["content"]))
    except Exception as exc:
        logger.warning("본문 수집 실패로 제외: %s (%s)", article["url"], exc)
        article["content"] = ""
        article["content_ok"] = False
    return article


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "자연스러운 한국어 요약 제목"},
        "summary": {"type": "string", "description": "기사의 중요한 내용을 담은 한국어 2~4문장"},
    },
    "required": ["title", "summary"],
    "additionalProperties": False,
}

SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 0,
            "maxItems": MAX_SUMMARIES,
        }
    },
    "required": ["selected_ids"],
    "additionalProperties": False,
}


def parse_summary(raw):
    """Structured Output을 검증하고 화면에 JSON 코드가 노출되지 않게 한다."""
    data = json.loads(raw)
    title = str(data.get("title", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not title or not summary:
        raise ValueError("title 또는 summary가 비어 있습니다.")
    if not re.search(r"[가-힣]", title) or not re.search(r"[가-힣]", summary):
        raise ValueError("한국어 제목 또는 요약이 생성되지 않았습니다.")
    if len(summary) < 40:
        raise ValueError("요약이 지나치게 짧습니다.")
    return title[:200], summary


def summarize(client, article):
    prompt = f"""다음 반도체/기술 기사를 한국어로 요약하세요. 제공된 내용만 사용하고 추측하지 마세요.
내용이 제목이나 짧은 설명뿐이면 그 범위만 요약하세요. title은 한국어 요약 제목, summary는 2~4문장입니다.
반드시 다른 문구나 마크다운 없이 {{"title":"...","summary":"..."}} JSON 객체만 출력하세요.

원문 제목: {article['title']}
원문 내용: {article['content']}"""
    last_error = None
    for attempt in range(1, 3):
        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions="당신은 정확하고 간결한 한국어 반도체 뉴스 편집자입니다.",
                input=prompt,
                reasoning={"effort": "minimal"},
                max_output_tokens=1_200,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "article_summary",
                        "strict": True,
                        "schema": SUMMARY_SCHEMA,
                    }
                },
            )
            if response.status != "completed" or not response.output_text.strip():
                raise ValueError(f"불완전한 응답: status={response.status}")
            title, summary = parse_summary(response.output_text)
            article["summary_ok"] = True
            break
        except Exception as exc:
            last_error = exc
            logger.warning("LLM 요약 %d차 실패: %s (%s)", attempt, article["url"], exc)
    else:
        # 실패 결과는 Discord에 절대 전송하지 않는다.
        title, summary = "", ""
        article["summary_ok"] = False
        logger.error("LLM 요약 최종 실패: %s (%s)", article["url"], last_error)
    article.update(summary_title=title, summary=summary)
    return article


def select_important(client, articles, source):
    """반도체와 직접 관련된 중요 기사만 0~5개 선별한다."""
    if not articles:
        return []

    candidates = [
        f"ID {index}\n제목: {article['title']}\n내용: {article.get('content', '')[:1_500]}"
        for index, article in enumerate(articles, 1)
    ]
    prompt = f"""다음 {source} 기사 후보에서 반도체 산업과 직접 관련된 중요 기사만 최대 {MAX_SUMMARIES}개 선택하세요.

반드시 포함 가능한 주제:
- 반도체 공정, 장비, 소재, 소자, 설계, 메모리, 파운드리, 패키징
- 반도체 기업의 투자, 생산, 수율, 공급망, 기술 경쟁
- AI 반도체 칩, GPU, NPU, ASIC 자체가 기사의 핵심인 경우

반드시 제외할 주제:
- 일반 AI 서비스, 챗봇, 통신 서비스, 정부 서비스 사업자 선정
- 바이오·신약 AI, 일반 소프트웨어·플랫폼·소비자 제품
- 반도체가 한두 문장 언급될 뿐 기사의 핵심이 아닌 경우
- 같은 사건을 다룬 중복 기사와 본문 정보가 부족한 기사

규칙:
- 중요 기사가 부족하면 5개를 채우지 말고 0~{MAX_SUMMARIES}개만 선택하세요.
- 직접 관련성이 불확실하면 제외하세요.
- 중요한 순서대로 서로 다른 ID만 반환하세요.

기사 후보:
{chr(10).join(candidates)}"""
    last_error = None
    for attempt in range(1, 3):
        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions="당신은 반도체 산업과 무관한 일반 AI·IT 뉴스를 엄격히 제외하는 편집장입니다.",
                input=prompt,
                reasoning={"effort": "minimal"},
                max_output_tokens=600,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "important_article_selection",
                        "strict": True,
                        "schema": SELECTION_SCHEMA,
                    }
                },
            )
            if response.status != "completed" or not response.output_text.strip():
                raise ValueError(f"불완전한 선별 응답: status={response.status}")
            selected_ids = json.loads(response.output_text).get("selected_ids", [])
            if len(selected_ids) > MAX_SUMMARIES or len(set(selected_ids)) != len(selected_ids):
                raise ValueError("선택 개수 또는 중복 ID가 올바르지 않습니다.")
            if any(not isinstance(value, int) or value < 1 or value > len(articles) for value in selected_ids):
                raise ValueError("선택 ID가 후보 범위를 벗어났습니다.")
            selected = [articles[value - 1] for value in selected_ids]
            logger.info("%s: 후보 %d건 중 반도체 직접 관련 기사 ID %s 선별",
                        source, len(articles), selected_ids)
            return selected
        except Exception as exc:
            last_error = exc
            logger.warning("%s 중요 기사 선별 %d차 실패: %s", source, attempt, exc)
    logger.error("%s 중요 기사 선별 최종 실패: %s", source, last_error)
    return None

def load_sent():
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("urls", []))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return set()


def save_sent(urls):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({"urls": sorted(urls)[-2000:]}, ensure_ascii=False, indent=2), encoding="utf-8")


def block(index, article):
    # URL을 꺾쇠로 감싸 Discord의 자동 링크 미리보기(Embed)를 억제한다.
    return (
        f"{index}. **{article['summary_title']}**\n"
        f"{article['summary']}\n"
        f"원문: <{article['url']}>"
    )


def messages(source, articles):
    date = datetime.now().strftime("%-m/%-d")
    output, current = [], f"#{source}\n- {date} 요약"
    for index, article in enumerate(articles, 1):
        text = block(index, article)
        if len(current) + len(text) + 2 <= 1900:
            current += "\n\n" + text
            continue
        output.append(current)
        header = f"#{source} (계속)\n- {date} 요약"
        room = 1900 - len(header) - len(article["url"]) - len(article["summary_title"]) - 50
        if len(text) > 1800:
            text = block(index, {**article, "summary": article["summary"][:max(room, 100)] + "…"})
        current = header + "\n\n" + text
    return output + [current]


def send(articles, webhook, source):
    if not articles:
        logger.info("%s: 새 기사 없음", source)
        return False
    if not webhook:
        logger.error("%s: Discord Webhook 미설정", source)
        return False
    for part, content in enumerate(messages(source, articles), 1):
        try:
            response = requests.post(webhook, json={"username": "반도체뉴스봇", "content": content}, timeout=20)
            if response.status_code not in (200, 204):
                # requests 예외에는 비밀값인 Webhook URL이 포함될 수 있으므로 직접 처리한다.
                logger.error("%s Discord 응답 오류: HTTP %d", source, response.status_code)
                return False
            logger.info("%s Discord 발송 완료 (%d부, %d자)", source, part, len(content))
        except Exception as exc:
            # 예외 문자열과 traceback에 Webhook URL이 노출되지 않게 유형만 기록한다.
            logger.error("%s Discord 발송 실패: %s", source, type(exc).__name__)
            return False
    return True


def save_results(results):
    Path("data").mkdir(exist_ok=True)
    path = Path(f"data/news_{datetime.now():%Y%m%d_%H%M}.json")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY가 설정되지 않았습니다.")
        return 1
    missing_webhooks = [source for source, webhook in WEBHOOKS.values() if not webhook]
    if missing_webhooks:
        logger.error("Discord Webhook 미설정: %s", ", ".join(missing_webhooks))
        return 1
    results, sent_urls, client = await crawl_all(), load_sent(), OpenAI(api_key=OPENAI_API_KEY)
    sent_count = 0
    had_error = False
    for key, crawled in results.items():
        source, webhook = WEBHOOKS[key]
        fresh_candidates = [article for article in crawled if article["url"] not in sent_urls]
        if not fresh_candidates:
            logger.info("%s: 새 기사 없음 (수집 %d건)", source, len(crawled))
            continue

        enriched = await asyncio.gather(
            *(asyncio.to_thread(fetch_article, article) for article in fresh_candidates)
        )
        usable = [article for article in enriched if article.get("content_ok")]
        deduplicated = deduplicate_topics(usable)
        logger.info("%s: 신규 %d건 → 본문 확보 %d건 → 유사 주제 제거 후 %d건",
                    source, len(fresh_candidates), len(usable), len(deduplicated))

        selected = select_important(client, deduplicated, source)
        if selected is None:
            had_error = True
            continue
        if not selected:
            logger.info("%s: 반도체 직접 관련 중요 기사 없음", source)
            results[key] = []
            sent_urls.update(article["url"] for article in fresh_candidates)
            save_sent(sent_urls)
            continue

        summarized = [summarize(client, article) for article in selected]
        results[key] = summarized
        if not all(article.get("summary_ok") for article in summarized):
            logger.error("%s: LLM 요약 실패 기사가 있어 Discord 발송을 건너뜁니다.", source)
            had_error = True
            continue
        if send(summarized, webhook, source):
            # 전송된 기사 외의 중복·무관 기사도 검토 완료로 기록한다.
            sent_urls.update(article["url"] for article in fresh_candidates)
            save_sent(sent_urls)
            sent_count += len(summarized)
        else:
            had_error = True
    save_results(results)
    logger.info("실행 완료: 새 기사 %d건 전송", sent_count)
    return 1 if had_error else 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
