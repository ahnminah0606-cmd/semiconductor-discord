# semiconductor_news_crawler.py
# 반도체 뉴스 자동 크롤러 v2.0

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

# 환경 변수 로드 (.env 파일에서)
load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 로깅 설정: 파일 + 콘솔 동시 출력
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_filename = LOG_DIR / f"crawler_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


async def crawl_semiconductor_news_dynamic() -> list[dict]:
    """Playwright를 사용한 동적 크롤링 (JavaScript 렌더링 지원)"""
    from playwright.async_api import async_playwright

    news_items = []
    targets = [
        {
            "name": "전자신문 반도체",
            "url": "https://www.etnews.com/news/section.html?id1=01&id2=01",
            "article_selector": "article.news-item",
            "title_selector": "h4.news-title",
            "source": "전자신문",
        },
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for target in targets:
            try:
                logger.info(f"크롤링 시작: {target['name']}")
                await page.goto(target["url"], wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                articles = await page.query_selector_all(target["article_selector"])

                for article in articles[:10]:
                    try:
                        title_el = await article.query_selector(target["title_selector"])
                        link_el  = await article.query_selector("a")

                        if title_el and link_el:
                            title = (await title_el.inner_text()).strip()
                            href  = await link_el.get_attribute("href")
                            if title and href:
                                news_items.append({
                                    "source": target["source"],
                                    "title": title,
                                    "url": href if href.startswith("http") else f"https://www.etnews.com{href}",
                                    "crawled_at": datetime.now().isoformat(),
                                })
                    except Exception as e:
                        logger.warning(f"기사 파싱 오류: {e}")

                logger.info(f"{target['name']}: {len(articles)}개 기사 수집")

            except Exception as e:
                logger.error(f"크롤링 실패 ({target['name']}): {e}", exc_info=True)

        await browser.close()

    return news_items


def crawl_semiconductor_news_static() -> list[dict]:
    """requests + BeautifulSoup 기반 정적 크롤링 (playwright 백업용)"""
    from bs4 import BeautifulSoup

    news_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    targets = [
        {"name": "네이버 반도체", "url": "https://news.naver.com/main/list.naver?mode=LS2D&mid=shm&sid1=105&sid2=230", "source": "네이버뉴스"},
    ]

    for feed in targets:
        try:
            response = requests.get(feed["url"], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.select("ul.type06_headline li, ul.type06 li")

            for article in articles[:10]:
                link_el = article.select_one("dt:not(.photo) a")
                if link_el:
                    title = link_el.get_text(strip=True)
                    url   = link_el.get("href", "")
                    if title and url:
                        news_items.append({"source": feed["source"], "title": title, "url": url, "crawled_at": datetime.now().isoformat()})

            logger.info(f"{feed['name']}: {len(articles)}개 기사 수집")

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP 요청 실패 ({feed['name']}): {e}", exc_info=True)

    return news_items


def send_to_discord(news_items: list[dict], webhook_url: str) -> bool:
    """
    크롤링 결과를 Discord Webhook으로 발송 (Embed 형식)
    """
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL이 설정되지 않았습니다.")
        return False

    if not news_items:
        logger.warning("발송할 뉴스 아이템이 없습니다.")
        return False

    now_str = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")

    embeds = [{
        "title": f"반도체 산업 뉴스 | {now_str}",
        "description": f"오늘의 반도체 주요 뉴스 **{len(news_items)}건**을 자동으로 수집했습니다.",
        "color": 0x1565C0,
        "footer": {"text": "semiconductor-news-crawler | GitHub Actions 자동 실행"},
        "timestamp": datetime.utcnow().isoformat(),
    }]

    for i, item in enumerate(news_items[:9], 1):
        title_short = item["title"][:100] + ("..." if len(item["title"]) > 100 else "")
        embeds.append({
            "title": f"{i}. {title_short}",
            "url": item["url"],
            "description": f"출처: {item['source']}",
            "color": 0x43A047 if i % 2 == 0 else 0x1E88E5,
        })

    payload = {
        "username": "반도체뉴스봇",
        "embeds": embeds,
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Discord 발송 완료 ({len(news_items)}건)")
        return True
    except Exception as e:
        logger.error(f"Discord 발송 실패: {e}", exc_info=True)
        return False


def save_results(news_items: list[dict]) -> Path:
    """크롤링 결과를 JSON 파일로 저장"""
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    filename = data_dir / f"news_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(news_items, f, ensure_ascii=False, indent=2)
    logger.info(f"결과 저장: {filename} ({len(news_items)}건)")
    return filename


async def main():
    logger.info("=" * 60)
    logger.info("반도체 뉴스 크롤러 시작")
    logger.info("=" * 60)

    news_items = []

    try:
        news_items = await crawl_semiconductor_news_dynamic()
        logger.info(f"playwright 크롤링 완료: {len(news_items)}건")
    except ImportError:
        logger.warning("playwright 미설치. requests 기반 크롤링으로 전환합니다.")
        news_items = crawl_semiconductor_news_static()
    except Exception as e:
        logger.error(f"playwright 크롤링 실패: {e}. requests 기반으로 전환합니다.")
        news_items = crawl_semiconductor_news_static()

    if news_items:
        save_results(news_items)
        send_to_discord(news_items, DISCORD_WEBHOOK_URL)
    else:
        logger.warning("수집된 뉴스가 없습니다.")

    logger.info("크롤러 실행 완료")
    return len(news_items)


if __name__ == "__main__":
    asyncio.run(main())
