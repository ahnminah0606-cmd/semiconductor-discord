# semiconductor_news_crawler.py
# 반도체 뉴스 자동 크롤러 v3.0
#
# 구성
# 1. 기존 반도체 뉴스
# 2. TrendForce Semiconductors
# 3. SemiAnalysis
#
# 각 정보원을 별도의 Discord Webhook으로 전송

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


# ============================================================
# 환경 변수
# ============================================================

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    ""
)

DISCORD_WEBHOOK_TRENDFORCE = os.getenv(
    "DISCORD_WEBHOOK_TRENDFORCE",
    ""
)

DISCORD_WEBHOOK_SEMIANALYSIS = os.getenv(
    "DISCORD_WEBHOOK_SEMIANALYSIS",
    ""
)


# ============================================================
# 로깅
# ============================================================

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_filename = (
    LOG_DIR
    / f"crawler_{datetime.now().strftime('%Y%m%d')}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            log_filename,
            encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


# ============================================================
# 공통 함수
# ============================================================

def remove_duplicates(
    news_items: list[dict]
) -> list[dict]:
    """
    URL 기준 중복 제거
    """

    unique = {}

    for item in news_items:
        url = item.get("url")

        if not url:
            continue

        unique[url] = item

    return list(unique.values())


def make_news_item(
    source: str,
    title: str,
    url: str,
) -> dict:
    """
    모든 사이트의 데이터 형식을 동일하게 맞춤
    """

    return {
        "source": source,
        "title": title.strip(),
        "url": url,
        "crawled_at": datetime.now().isoformat(),
    }


# ============================================================
# TrendForce
# ============================================================

async def crawl_trendforce(
    context
) -> list[dict]:

    url = (
        "https://www.trendforce.com/"
        "news/category/semiconductors/"
    )

    logger.info("=" * 50)
    logger.info("TrendForce 크롤링 시작")

    page = await context.new_page()

    news_items = []

    try:

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(3000)

        links = page.locator("a")

        count = await links.count()

        for i in range(count):

            try:

                link = links.nth(i)

                title = (
                    await link.inner_text()
                ).strip()

                href = await link.get_attribute(
                    "href"
                )

                if not title or not href:
                    continue

                # 너무 짧은 메뉴/카테고리 링크 제거
                if len(title) < 20:
                    continue

                full_url = urljoin(
                    url,
                    href
                )

                # TrendForce 뉴스 페이지가 아닌 링크 제거
                if (
                    "trendforce.com/news/"
                    not in full_url
                ):
                    continue

                # 카테고리 페이지 자체 제거
                if (
                    "/category/"
                    in full_url
                ):
                    continue

                lowered = title.lower()

                # 사이트 메뉴 제거
                blocked_titles = [
                    "view more",
                    "semiconductors",
                    "latest",
                    "display",
                    "energy",
                    "telecommunications",
                ]

                if any(
                    blocked == lowered
                    for blocked
                    in blocked_titles
                ):
                    continue

                news_items.append(
                    make_news_item(
                        "TrendForce",
                        title,
                        full_url
                    )
                )

            except Exception:
                continue

        news_items = remove_duplicates(
            news_items
        )

        # 너무 많이 전송하지 않도록 제한
        news_items = news_items[:5]

        logger.info(
            f"TrendForce: "
            f"{len(news_items)}개 기사 수집"
        )

    except Exception as e:

        logger.error(
            f"TrendForce 크롤링 실패: {e}",
            exc_info=True
        )

    finally:

        await page.close()

    return news_items


# ============================================================
# SemiAnalysis
# ============================================================

async def crawl_semianalysis(
    context
) -> list[dict]:

    # 현재 SemiAnalysis archive
    url = (
        "https://newsletter."
        "semianalysis.com/archive"
    )

    logger.info("=" * 50)
    logger.info("SemiAnalysis 크롤링 시작")

    page = await context.new_page()

    news_items = []

    try:

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(3000)

        links = page.locator("a")

        count = await links.count()

        for i in range(count):

            try:

                link = links.nth(i)

                title = (
                    await link.inner_text()
                ).strip()

                href = await link.get_attribute(
                    "href"
                )

                if not title or not href:
                    continue

                # 메뉴 / 짧은 텍스트 제외
                if len(title) < 20:
                    continue

                full_url = urljoin(
                    url,
                    href
                )

                # 실제 게시물 주소만 사용
                if (
                    "/p/"
                    not in full_url
                ):
                    continue

                if (
                    "semianalysis.com"
                    not in full_url
                ):
                    continue

                news_items.append(
                    make_news_item(
                        "SemiAnalysis",
                        title,
                        full_url
                    )
                )

            except Exception:
                continue

        news_items = remove_duplicates(
            news_items
        )

        # 최신 글 최대 5개
        news_items = news_items[:5]

        logger.info(
            f"SemiAnalysis: "
            f"{len(news_items)}개 글 수집"
        )

    except Exception as e:

        logger.error(
            f"SemiAnalysis 크롤링 실패: {e}",
            exc_info=True
        )

    finally:

        await page.close()

    return news_items


# ============================================================
# 기존 전자신문
# ============================================================

async def crawl_etnews(
    context
) -> list[dict]:

    url = (
        "https://www.etnews.com/"
        "news/section.html?"
        "id1=01&id2=01"
    )

    logger.info("=" * 50)
    logger.info("전자신문 크롤링 시작")

    page = await context.new_page()

    news_items = []

    try:

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(3000)

        # 기존 selector 우선 사용
        articles = await page.query_selector_all(
            "article.news-item"
        )

        for article in articles[:5]:

            try:

                title_el = await article.query_selector(
                    "h4.news-title"
                )

                link_el = await article.query_selector(
                    "a"
                )

                if not title_el or not link_el:
                    continue

                title = (
                    await title_el.inner_text()
                ).strip()

                href = (
                    await link_el.get_attribute(
                        "href"
                    )
                )

                if not title or not href:
                    continue

                full_url = urljoin(
                    "https://www.etnews.com/",
                    href
                )

                news_items.append(
                    make_news_item(
                        "전자신문",
                        title,
                        full_url
                    )
                )

            except Exception as e:

                logger.warning(
                    f"전자신문 기사 파싱 오류: {e}"
                )

        news_items = remove_duplicates(
            news_items
        )

        logger.info(
            f"전자신문: "
            f"{len(news_items)}개 기사 수집"
        )

        if not news_items:

            logger.warning(
                "전자신문 기사 0건 - "
                "사이트 구조가 변경되었을 "
                "가능성이 있습니다."
            )

    except Exception as e:

        logger.error(
            f"전자신문 크롤링 실패: {e}",
            exc_info=True
        )

    finally:

        await page.close()

    return news_items


# ============================================================
# 모든 사이트 크롤링
# ============================================================

async def crawl_all_sites():

    from playwright.async_api import (
        async_playwright
    )

    results = {
        "etnews": [],
        "trendforce": [],
        "semianalysis": [],
    }

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context(

            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            ),

            viewport={
                "width": 1440,
                "height": 900,
            }
        )

        # ----------------------------------------------------
        # 사이트별로 독립 실행
        # ----------------------------------------------------

        try:
            results["etnews"] = (
                await crawl_etnews(
                    context
                )
            )
        except Exception as e:
            logger.error(
                f"전자신문 전체 오류: {e}"
            )

        try:
            results["trendforce"] = (
                await crawl_trendforce(
                    context
                )
            )
        except Exception as e:
            logger.error(
                f"TrendForce 전체 오류: {e}"
            )

        try:
            results["semianalysis"] = (
                await crawl_semianalysis(
                    context
                )
            )
        except Exception as e:
            logger.error(
                f"SemiAnalysis 전체 오류: {e}"
            )

        await browser.close()

    return results


# ============================================================
# Discord
# ============================================================

def send_to_discord(
    news_items: list[dict],
    webhook_url: str,
    channel_name: str,
) -> bool:

    if not webhook_url:

        logger.error(
            f"{channel_name}: "
            "Discord Webhook이 "
            "설정되지 않았습니다."
        )

        return False

    if not news_items:

        logger.warning(
            f"{channel_name}: "
            "발송할 뉴스가 없습니다."
        )

        return False

    now_str = datetime.now().strftime(
        "%Y년 %m월 %d일 %H:%M"
    )

    # --------------------------------------------------------
    # 첫 Embed
    # --------------------------------------------------------

    embeds = [
        {
            "title": (
                f"{channel_name} | "
                f"{now_str}"
            ),

            "description": (
                f"새로운 자료 "
                f"**{len(news_items)}건**을 "
                "수집했습니다."
            ),

            "color": 0x1565C0,

            "footer": {
                "text": (
                    "semiconductor-news-crawler "
                    "| GitHub Actions"
                )
            },

            "timestamp": (
                datetime.utcnow()
                .isoformat()
            ),
        }
    ]

    # --------------------------------------------------------
    # 기사 Embed
    # --------------------------------------------------------

    for i, item in enumerate(
        news_items[:5],
        1
    ):

        title = item.get(
            "title",
            "제목 없음"
        )

        title_short = (
            title[:150]
            + (
                "..."
                if len(title) > 150
                else ""
            )
        )

        embeds.append(
            {
                "title": (
                    f"{i}. {title_short}"
                ),

                "url": item["url"],

                "description": (
                    f"출처: "
                    f"{item['source']}"
                ),

                "color": (
                    0x43A047
                    if i % 2 == 0
                    else 0x1E88E5
                ),
            }
        )

    payload = {
        "username": "반도체뉴스봇",
        "embeds": embeds,
    }

    try:

        response = requests.post(
            webhook_url,
            json=payload,
            timeout=15
        )

        logger.info(
            f"{channel_name} "
            f"Discord 응답 코드: "
            f"{response.status_code}"
        )

        # Discord Webhook 성공은 보통 204
        if response.status_code not in (
            200,
            204
        ):

            logger.error(
                f"{channel_name} "
                f"Discord 응답: "
                f"{response.text}"
            )

        response.raise_for_status()

        logger.info(
            f"{channel_name}: "
            f"Discord 발송 완료 "
            f"({len(news_items)}건)"
        )

        return True

    except Exception as e:

        logger.error(
            f"{channel_name}: "
            f"Discord 발송 실패: {e}",
            exc_info=True
        )

        return False


# ============================================================
# 결과 저장
# ============================================================

def save_results(
    results: dict
) -> Path:

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    filename = (
        data_dir
        / (
            "news_"
            + datetime.now().strftime(
                "%Y%m%d_%H%M"
            )
            + ".json"
        )
    )

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )

    total = sum(
        len(items)
        for items in results.values()
    )

    logger.info(
        f"결과 저장: {filename} "
        f"(총 {total}건)"
    )

    return filename


# ============================================================
# 메인
# ============================================================

async def main():

    logger.info("=" * 60)
    logger.info(
        "반도체 뉴스 크롤러 v3.0 시작"
    )
    logger.info("=" * 60)

    try:

        results = await crawl_all_sites()

    except ImportError:

        logger.error(
            "Playwright가 설치되어 있지 않습니다."
        )

        return 0

    except Exception as e:

        logger.error(
            f"전체 크롤러 실행 오류: {e}",
            exc_info=True
        )

        return 0

    # --------------------------------------------------------
    # 사이트별 결과
    # --------------------------------------------------------

    etnews_items = results.get(
        "etnews",
        []
    )

    trendforce_items = results.get(
        "trendforce",
        []
    )

    semianalysis_items = results.get(
        "semianalysis",
        []
    )

    logger.info("=" * 60)

    logger.info(
        f"전자신문: "
        f"{len(etnews_items)}건"
    )

    logger.info(
        f"TrendForce: "
        f"{len(trendforce_items)}건"
    )

    logger.info(
        f"SemiAnalysis: "
        f"{len(semianalysis_items)}건"
    )

    total = (
        len(etnews_items)
        + len(trendforce_items)
        + len(semianalysis_items)
    )

    logger.info(
        f"전체 수집: {total}건"
    )

    logger.info("=" * 60)

    # --------------------------------------------------------
    # 결과가 하나라도 있으면 JSON 저장
    # --------------------------------------------------------

    if total > 0:

        save_results(
            results
        )

    else:

        logger.error(
            "모든 사이트에서 "
            "수집된 뉴스가 없습니다."
        )

    # --------------------------------------------------------
    # Discord 각각 전송
    # --------------------------------------------------------

    if etnews_items:

        send_to_discord(
            etnews_items,
            DISCORD_WEBHOOK_URL,
            "전자신문 반도체 뉴스",
        )

    if trendforce_items:

        send_to_discord(
            trendforce_items,
            DISCORD_WEBHOOK_TRENDFORCE,
            "TrendForce 반도체 뉴스",
        )

    if semianalysis_items:

        send_to_discord(
            semianalysis_items,
            DISCORD_WEBHOOK_SEMIANALYSIS,
            "SemiAnalysis",
        )

    logger.info("=" * 60)
    logger.info(
        "크롤러 실행 완료"
    )
    logger.info("=" * 60)

    return total


if __name__ == "__main__":
    asyncio.run(main())