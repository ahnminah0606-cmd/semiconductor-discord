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
    return list({x["url"]: x for x in items if x.get("url")}.values())[:5]


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
    """네이버 IT/과학 > 반도체 최신 기사 5개를 수집한다."""
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
    """본문 → JSON-LD → meta description → 제목 순 fallback."""
    try:
        response = requests.get(article["url"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        description = meta(soup, 'meta[property="og:description"]', 'meta[name="description"]',
                           'meta[name="twitter:description"]')
        body = trafilatura.extract(response.text, include_comments=False, include_tables=False,
                                   favor_precision=True) or json_ld_body(soup)
        article["description"] = description or article["description"]
        article["content"] = " ".join((body or description or article["title"]).split())[:12_000]
        logger.info("본문 수집: %s (%d자)", article["url"], len(article["content"]))
    except Exception as exc:
        logger.warning("본문 수집 실패, fallback 사용: %s (%s)", article["url"], exc)
        article["content"] = article["description"] or article["title"]
    return article


def parse_summary(raw, fallback):
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if data.get("title") and data.get("summary"):
            return str(data["title"]).strip(), str(data["summary"]).strip()
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    lines = [x.strip() for x in cleaned.splitlines() if x.strip()]
    return (lines[0][:100] if lines else fallback[:100], " ".join(lines[1:]) or cleaned)


def summarize(client, article):
    prompt = f"""다음 반도체/기술 기사를 한국어로 요약하세요. 제공된 내용만 사용하고 추측하지 마세요.
내용이 제목이나 짧은 설명뿐이면 그 범위만 요약하세요. title은 한국어 요약 제목, summary는 2~4문장입니다.
반드시 다른 문구나 마크다운 없이 {{"title":"...","summary":"..."}} JSON 객체만 출력하세요.

원문 제목: {article['title']}
원문 내용: {article['content']}"""
    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions="당신은 정확하고 간결한 한국어 반도체 뉴스 편집자입니다.",
            input=prompt,
            max_output_tokens=500,
        )
        title, summary = parse_summary(response.output_text, article["title"])
        article["summary_ok"] = True
    except Exception as exc:
        logger.error("LLM 요약 실패: %s (%s)", article["url"], exc)
        title = article["title"]
        summary = article["description"] or "요약을 생성하지 못했습니다. 원문을 확인해 주세요."
        article["summary_ok"] = False
    article.update(summary_title=title, summary=summary)
    return article


def load_sent():
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("urls", []))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return set()


def save_sent(urls):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({"urls": sorted(urls)[-2000:]}, ensure_ascii=False, indent=2), encoding="utf-8")


def embed_payloads(source, articles):
    """기사 5개를 한 Discord 메시지의 Embed 카드로 묶는다."""
    date = datetime.now().strftime("%-m/%-d")
    colors = {"NaverNews": 0x03C75A, "TrendForce": 0x1565C0, "SemiAnalysis": 0x7E57C2}
    output, embeds, total_chars = [], [], 0
    for index, article in enumerate(articles, 1):
        title = f"{index}. {article['summary_title']}"[:256]
        description = article["summary"][:4096]
        embed_chars = len(title) + len(description)
        # Discord는 메시지당 Embed 10개, Embed 전체 텍스트 6,000자를 허용한다.
        if embeds and (len(embeds) >= 10 or total_chars + embed_chars > 5_800):
            output.append({"content": f"#{source}\n- {date} 요약", "embeds": embeds})
            embeds, total_chars = [], 0
        embeds.append({
            "title": title,
            "description": description,
            "color": colors.get(source, 0x1565C0),
        })
        total_chars += embed_chars
    if embeds:
        continuation = " (계속)" if output else ""
        output.append({"content": f"#{source}{continuation}\n- {date} 요약", "embeds": embeds})
    return output


def send(articles, webhook, source):
    if not articles:
        logger.info("%s: 새 기사 없음", source)
        return False
    if not webhook:
        logger.error("%s: Discord Webhook 미설정", source)
        return False
    for part, payload in enumerate(embed_payloads(source, articles), 1):
        try:
            response = requests.post(webhook, json={"username": "반도체뉴스봇", **payload}, timeout=20)
            response.raise_for_status()
            logger.info("%s Discord Embed 발송 완료 (%d부, %d개)", source, part, len(payload["embeds"]))
        except Exception as exc:
            logger.error("%s Discord 발송 실패: %s", source, exc, exc_info=True)
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
        fresh = [article for article in crawled if article["url"] not in sent_urls]
        if not fresh:
            logger.info("%s: 새 기사 없음 (수집 %d건)", source, len(crawled))
            continue
        enriched = await asyncio.gather(*(asyncio.to_thread(fetch_article, article) for article in fresh))
        summarized = [summarize(client, article) for article in enriched]
        results[key] = summarized
        if not all(article.get("summary_ok") for article in summarized):
            logger.error("%s: LLM 요약 실패 기사가 있어 Discord 발송을 건너뜁니다.", source)
            had_error = True
            continue
        if send(summarized, webhook, source):
            sent_urls.update(article["url"] for article in summarized)
            save_sent(sent_urls)  # 전송 성공한 URL만 기록한다.
            sent_count += len(summarized)
        else:
            had_error = True
    save_results(results)
    logger.info("실행 완료: 새 기사 %d건 전송", sent_count)
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
