from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from backend.ai import Judgment, OpenRouterJudge
from backend.app import create_app
from backend.config import Settings
from backend.monitor import status_for_evidence
from backend.sources import Candidate, SourceCollector, parse_bing_html, parse_google_news_xml, parse_official_feed_xml, parse_twitter_json


def settings(tmp_path: Path, **changes) -> Settings:
    base = Settings(
        database_path=tmp_path / "test.db",
        openrouter_api_key="test-key",
        openrouter_model="test-model",
        twitterapi_key="test-key",
        official_rss_urls=(),
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        alert_email="",
        smtp_starttls=True,
        smtp_ssl=False,
        scheduler_enabled=False,
    )
    return replace(base, **changes)


def test_source_parsers():
    bing = parse_bing_html('<li class="b_algo"><h2><a href="https://example.org/news">新模型发布</a></h2><div class="b_caption"><p>正式公告</p></div></li>')
    assert bing[0].source_group == "example.org"
    assert bing[0].snippet == "正式公告"

    xml = """<rss><channel><item><title>AI 新消息</title><link>https://news.google.com/a</link>
    <description><![CDATA[<b>摘要</b>]]></description><source url="https://example.com">示例媒体</source>
    </item></channel></rss>"""
    news = parse_google_news_xml(xml)
    assert news[0].source_group == "example.com"
    assert news[0].snippet == "摘要"

    tweets = parse_twitter_json({"tweets": [{"id": "123", "text": "新模型发布", "author": {"userName": "example"}}]})
    assert tweets[0].url == "https://x.com/example/status/123"
    assert tweets[0].source_group == "x:example"


def test_verification_threshold():
    assert status_for_evidence({"x:a"}, False) == "pending"
    assert status_for_evidence({"x:a", "x:b"}, False) == "pending"
    assert status_for_evidence({"x:a", "example.org"}, False) == "verified"
    assert status_for_evidence({"openai.com"}, False) == "pending"
    assert status_for_evidence({"official:openai.com"}, False) == "verified"
    assert status_for_evidence({"official:openai.com"}, True) == "suspicious"
    assert status_for_evidence({"official:openai.com", "openai.com"}, False) == "verified"


def test_api_crud_and_missing_ai(tmp_path):
    app = create_app(settings(tmp_path, openrouter_api_key=""))
    with TestClient(app) as client:
        response = client.post("/api/rules", json={"query": "AI 编程", "kind": "topic"})
        assert response.status_code == 201
        rule = response.json()
        assert rule["interval_minutes"] == 30
        assert client.get("/api/rules").json()[0]["query"] == "AI 编程"
        assert client.patch(f"/api/rules/{rule['id']}", json={"enabled": False}).json()["enabled"] == 0
        assert client.patch(f"/api/rules/{rule['id']}", json={"query": None}).status_code == 422
        scan = client.post(f"/api/rules/{rule['id']}/scan").json()
        assert scan["status"] == "error"
        assert "OPENROUTER_API_KEY" in scan["message"]
        assert client.get("/api/status").json()["ai_configured"] is False
        assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
        assert client.get("/api/rules").json() == []


def test_multi_source_confirmation_and_notification_dedup(tmp_path):
    app = create_app(settings(tmp_path, smtp_host="smtp.test", smtp_from="alerts@test.com", alert_email="me@test.com"))
    monitor = app.state.monitor
    sent = []
    monitor._send_email = lambda item: sent.append(item["event_id"])

    async def empty(_query):
        return []

    async def web(_query):
        return [Candidate("必应网页搜索", "example.org", "https://example.org/model", "新模型发布", "一家公司发布新模型")]

    async def tweet(_query):
        return [Candidate("X · @reporter", "x:reporter", "https://x.com/reporter/status/1", "新模型发布", "一家公司发布新模型")]

    async def judge(_query, _kind, _candidate, recent):
        return Judgment(True, False, "一家公司发布了新模型。", "网页与 X 提供相互印证的线索。", recent[0]["id"] if recent else 0, 78)

    monitor.sources.google_news = empty
    monitor.sources.bing = web
    monitor.sources.twitter = tweet
    monitor.sources.official_rss = empty
    monitor.judge.judge = judge

    with TestClient(app) as client:
        rule_id = client.post("/api/rules", json={"query": "新模型", "kind": "keyword"}).json()["id"]
        first = client.post(f"/api/rules/{rule_id}/scan").json()
        assert first["status"] == "ok"
        assert first["new_events"] == 1
        events = client.get("/api/events").json()
        assert len(events) == 1
        assert events[0]["status"] == "verified"
        assert len(events[0]["evidence"]) == 2
        alerts = client.get("/api/notifications").json()
        assert len(alerts) == 1
        assert alerts[0]["email_status"] == "待发送"

        asyncio.run(monitor.retry_emails())
        assert sent == [events[0]["id"]]
        assert client.get("/api/notifications").json()[0]["email_status"] == "已发送"
        asyncio.run(monitor.retry_emails())
        assert len(sent) == 1

        second = client.post(f"/api/rules/{rule_id}/scan").json()
        assert second["new_events"] == 0
        assert len(client.get("/api/notifications").json()) == 1
        assert client.post(f"/api/notifications/{alerts[0]['id']}/read").status_code == 200
        assert client.get("/api/status").json()["unread"] == 0


def test_suspicious_evidence_never_confirms(tmp_path):
    app = create_app(settings(tmp_path))
    monitor = app.state.monitor

    async def empty(_query):
        return []

    async def suspicious(_query):
        return [Candidate("X · @fake", "x:fake", "https://x.com/fake/status/2", "假冒公告", "没有出处")]

    async def judge(*_args):
        return Judgment(True, True, "疑似假冒公告。", "缺少原始来源。", 0, 30)

    monitor.sources.google_news = empty
    monitor.sources.bing = empty
    monitor.sources.twitter = suspicious
    monitor.sources.official_rss = empty
    monitor.judge.judge = judge

    with TestClient(app) as client:
        rule_id = client.post("/api/rules", json={"query": "假冒公告", "kind": "keyword"}).json()["id"]
        client.post(f"/api/rules/{rule_id}/scan")
        assert client.get("/api/events").json()[0]["status"] == "suspicious"
        assert client.get("/api/notifications").json() == []


def test_openrouter_request_uses_structured_output(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "relevant": True, "suspicious": False, "summary": "新模型发布。",
                "reason": "与关键词相关。", "matched_event_id": 0, "heat": 68,
            }, ensure_ascii=False)}}]}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr("backend.ai.httpx.AsyncClient", FakeClient)
    judge = OpenRouterJudge("test-secret", "google/gemini-2.5-flash")
    candidate = Candidate("X · @test", "x:test", "https://x.com/test/status/1", "新模型发布", "公告")
    result = asyncio.run(judge.judge("新模型", "keyword", candidate, []))
    assert result.relevant is True
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["provider"]["require_parameters"] is True


def test_twitterapi_request_matches_documented_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"tweets": [{"id": "123", "text": "AI 新消息", "author": {"userName": "author"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["headers"] = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, url, params):
            captured.update(url=url, params=params)
            return FakeResponse()

    monkeypatch.setattr("backend.sources.httpx.AsyncClient", FakeClient)
    tweets = asyncio.run(SourceCollector("test-x-key").twitter("AI"))
    assert len(tweets) == 1
    assert captured["url"] == "https://api.twitterapi.io/twitter/tweet/advanced_search"
    assert captured["headers"]["X-API-Key"] == "test-x-key"
    assert captured["params"]["queryType"] == "Latest"
    assert "since_time:" in captured["params"]["query"]


def test_one_source_failure_does_not_hide_other_results(tmp_path):
    app = create_app(settings(tmp_path))
    monitor = app.state.monitor

    async def broken(_query):
        raise RuntimeError("来源暂时不可用")

    async def empty(_query):
        return []

    async def news(_query):
        return [Candidate("Google 新闻 · 示例", "example.com", "https://news.google.com/a", "新进展", "新进展摘要")]

    async def judge(*_args):
        return Judgment(True, False, "新进展。", "仅有一个来源。", 0, 60)

    monitor.sources.bing = broken
    monitor.sources.google_news = news
    monitor.sources.twitter = empty
    monitor.sources.official_rss = empty
    monitor.judge.judge = judge

    with TestClient(app) as client:
        rule_id = client.post("/api/rules", json={"query": "新进展", "kind": "topic"}).json()["id"]
        result = client.post(f"/api/rules/{rule_id}/scan").json()
        assert result["status"] == "partial"
        assert "bing" in result["message"]
        assert client.get("/api/events").json()[0]["status"] == "pending"
        assert client.get("/api/status").json()["sources"]


def test_official_feed_requires_recent_original_url():
    from datetime import datetime, timezone
    from email.utils import format_datetime

    recent = format_datetime(datetime.now(timezone.utc))
    xml = f"""<rss><channel><item><title>新公告</title><link>https://openai.com/news/new</link>
    <description><![CDATA[<p>原始公告</p>]]></description><pubDate>{recent}</pubDate></item>
    <item><title>外部链接</title><link>https://fake.example/post</link><pubDate>{recent}</pubDate></item>
    </channel></rss>"""
    items = parse_official_feed_xml(xml, "https://openai.com/news/rss.xml")
    assert len(items) == 1
    assert items[0].source_group == "official:openai.com"
