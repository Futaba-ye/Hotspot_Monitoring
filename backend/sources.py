from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "HotspotMonitoring/1.0 (+local personal research; respectful polling)"}


@dataclass(frozen=True)
class Candidate:
    source: str
    source_group: str
    url: str
    title: str
    snippet: str
    published_at: str | None = None


def normalize_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value.split("#", 1)[0]


def domain(value: str) -> str:
    return (urlparse(value).hostname or "").removeprefix("www.").lower()


def parse_bing_html(html: str) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[Candidate] = []
    for result in soup.select("li.b_algo")[:15]:
        link = result.select_one("h2 a[href]")
        if not link:
            continue
        url = normalize_url(link.get("href", ""))
        if not url:
            continue
        description = result.select_one(".b_caption p") or result.select_one("p")
        results.append(Candidate(
            source="必应网页搜索",
            source_group=domain(url),
            url=url,
            title=link.get_text(" ", strip=True),
            snippet=description.get_text(" ", strip=True) if description else "",
        ))
    return results


def parse_google_news_xml(xml_text: str) -> list[Candidate]:
    root = ET.fromstring(xml_text)
    results: list[Candidate] = []
    for item in root.findall("./channel/item")[:20]:
        title = item.findtext("title", "").strip()
        url = normalize_url(item.findtext("link", "").strip())
        if not title or not url:
            continue
        source_element = item.find("source")
        publisher_url = source_element.get("url", "") if source_element is not None else ""
        publisher = source_element.text if source_element is not None else ""
        description = BeautifulSoup(item.findtext("description", ""), "html.parser").get_text(" ", strip=True)
        results.append(Candidate(
            source=f"Google 新闻 · {publisher or '未知发布者'}",
            source_group=domain(publisher_url) or domain(url),
            url=url,
            title=title,
            snippet=description,
            published_at=item.findtext("pubDate"),
        ))
    return results


def parse_twitter_json(payload: dict) -> list[Candidate]:
    results: list[Candidate] = []
    for tweet in payload.get("tweets", [])[:20]:
        if not isinstance(tweet, dict):
            continue
        author = tweet.get("author") or {}
        user_name = author.get("userName", "") if isinstance(author, dict) else ""
        text = re.sub(r"\s+", " ", tweet.get("text") or "").strip()
        tweet_id = str(tweet.get("id") or "")
        url = normalize_url(tweet.get("url") or f"https://x.com/{user_name}/status/{tweet_id}")
        if not text or not url:
            continue
        results.append(Candidate(
            source=f"X · @{user_name or '未知用户'}",
            source_group=f"x:{user_name.lower() or tweet_id}",
            url=url,
            title=text[:120],
            snippet=text,
            published_at=tweet.get("createdAt"),
        ))
    return results


def parse_official_feed_xml(xml_text: str, feed_url: str) -> list[Candidate]:
    root = ET.fromstring(xml_text)
    feed_domain = domain(feed_url)
    entries = root.findall("./channel/item")
    results: list[Candidate] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    for item in entries[:20]:
        title = (item.findtext("title") or "").strip()
        url = normalize_url((item.findtext("link") or "").strip())
        published = (item.findtext("pubDate") or "").strip()
        if not title or not url or domain(url) != feed_domain or not published:
            continue
        try:
            published_date = parsedate_to_datetime(published).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        if published_date < cutoff or published_date > datetime.now(timezone.utc) + timedelta(hours=1):
            continue
        description = BeautifulSoup(item.findtext("description", ""), "html.parser").get_text(" ", strip=True)
        results.append(Candidate(
            source=f"官方 RSS · {feed_domain}", source_group=f"official:{feed_domain}",
            url=url, title=title, snippet=description[:1500], published_at=published,
        ))
    return results


class SourceCollector:
    def __init__(self, twitterapi_key: str):
        self.twitterapi_key = twitterapi_key
        self._twitter_lock = asyncio.Lock()
        self._twitter_last_request = 0.0
        self._web_lock = asyncio.Lock()
        self._web_last_request = 0.0

    async def _wait_for_web_slot(self) -> None:
        delay = 10.0 - (time.monotonic() - self._web_last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        self._web_last_request = time.monotonic()

    async def bing(self, query: str) -> list[Candidate]:
        async with self._web_lock:
            await self._wait_for_web_slot()
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                response = await client.get("https://www.bing.com/search", params={"q": query, "count": 15})
                response.raise_for_status()
                return parse_bing_html(response.text)

    async def google_news(self, query: str) -> list[Candidate]:
        async with self._web_lock:
            await self._wait_for_web_slot()
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                response = await client.get(
                    "https://news.google.com/rss/search",
                    params={"q": f"{query} when:2d", "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
                )
                response.raise_for_status()
                return parse_google_news_xml(response.text)

    async def twitter(self, query: str) -> list[Candidate]:
        if not self.twitterapi_key:
            raise RuntimeError("尚未配置 TWITTERAPI_IO_KEY")
        async with self._twitter_lock:
            delay = 5.1 - (time.monotonic() - self._twitter_last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._twitter_last_request = time.monotonic()
            async with httpx.AsyncClient(timeout=20, headers={"X-API-Key": self.twitterapi_key}) as client:
                params = {"query": f"{query} since_time:{int(time.time() - 2 * 86400)}", "queryType": "Latest"}
                response = await client.get("https://api.twitterapi.io/twitter/tweet/advanced_search", params=params)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 6.0
                    await asyncio.sleep(min(max(delay, 5.1), 15.0))
                    self._twitter_last_request = time.monotonic()
                    response = await client.get("https://api.twitterapi.io/twitter/tweet/advanced_search", params=params)
                if response.status_code == 402:
                    raise RuntimeError("twitterapi.io 额度不足（HTTP 402）")
                if response.status_code == 429:
                    raise RuntimeError("twitterapi.io 请求过于频繁（HTTP 429）")
                response.raise_for_status()
                return parse_twitter_json(response.json())

    async def official_rss(self, feed_urls: tuple[str, ...]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for feed_url in feed_urls:
            if not normalize_url(feed_url):
                continue
            async with self._web_lock:
                await self._wait_for_web_slot()
                async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                    response = await client.get(feed_url)
                    response.raise_for_status()
                    candidates.extend(parse_official_feed_xml(response.text, feed_url))
        return candidates
