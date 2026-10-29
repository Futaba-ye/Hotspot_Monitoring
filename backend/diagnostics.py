from __future__ import annotations

import argparse
import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from .ai import OpenRouterJudge
from .config import get_settings
from .db import Database
from .monitor import Monitor, utc_now
from .sources import Candidate, SourceCollector


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {str(exc)[:160]}"


async def check_apis() -> None:
    settings = get_settings()
    if not settings.openrouter_api_key:
        print("OpenRouter：未配置")
    else:
        candidate = Candidate(
            source="连接测试", source_group="openai.com",
            url="https://openai.com/news/", title="OpenAI 官方新闻",
            snippet="这是接口连通性测试，不代表真实热点事件。",
        )
        try:
            result = await OpenRouterJudge(settings.openrouter_api_key, settings.openrouter_model).judge(
                "OpenAI", "topic", candidate, [],
            )
            print(f"OpenRouter：连接成功，结构化判读成功（模型：{settings.openrouter_model}，相关：{result.relevant}）")
        except Exception as exc:
            print(f"OpenRouter：失败，{error_text(exc)}")

    if not settings.twitterapi_key:
        print("X：未配置 TWITTERAPI_IO_KEY")
    else:
        try:
            tweets = await SourceCollector(settings.twitterapi_key).twitter("OpenAI")
            print(f"X：连接成功，获取 {len(tweets)} 条结果")
        except Exception as exc:
            print(f"X：失败，{error_text(exc)}")


def check_email() -> None:
    settings = get_settings()
    if not all([settings.smtp_host, settings.smtp_from, settings.alert_email]):
        print("邮件：配置不完整")
        return
    monitor = Monitor(Database(settings.database_path), settings)
    try:
        monitor._send_email({"title": "脉冲台连接测试", "summary": "SMTP 连接测试成功。此邮件不代表热点事件。"})
        print("邮件：发送成功，请检查收件箱")
    except Exception as exc:
        print(f"邮件：失败，{error_text(exc)}")


async def check_full_scan() -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as folder:
        probe_settings = replace(settings, database_path=Path(folder) / "probe.db", scheduler_enabled=False)
        database = Database(probe_settings.database_path)
        database.initialize()
        with database.connect() as connection:
            rule_id = connection.execute(
                "INSERT INTO rules(query,kind,interval_minutes,created_at) VALUES(?,?,?,?)",
                ("OpenAI", "topic", 30, utc_now()),
            ).lastrowid
        result = await Monitor(database, probe_settings).scan_rule(rule_id, force=True, per_source_limit=1)
        with database.connect() as connection:
            events = connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            source_runs = [dict(row) for row in connection.execute(
                "SELECT source,result_count,error FROM source_runs ORDER BY id"
            )]
        print(f"完整扫描：{result['status']}，生成 {events} 个事件")
        for source in source_runs:
            state = "成功" if not source["error"] else f"失败：{source['error'][:100]}"
            print(f"  {source['source']}：{state}，候选 {source['result_count']} 条")
        if result["status"] != "ok":
            print(f"扫描提示：{result['message'][:300]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="检测 OpenRouter、X 和邮件连接")
    parser.add_argument("--send-email", action="store_true", help="向 ALERT_EMAIL 发送一封测试邮件")
    parser.add_argument("--full-scan", action="store_true", help="使用临时数据库运行一次多来源真实扫描")
    args = parser.parse_args()
    if not args.full_scan:
        asyncio.run(check_apis())
    if args.send_email:
        check_email()
    if args.full_scan:
        asyncio.run(check_full_scan())


if __name__ == "__main__":
    main()
