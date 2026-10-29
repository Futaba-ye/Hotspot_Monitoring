from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from .ai import Judgment, OpenRouterJudge
from .config import Settings
from .db import Database
from .sources import Candidate, SourceCollector


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_official(group: str) -> bool:
    return group.startswith("official:") and bool(group.removeprefix("official:"))


def status_for_evidence(groups: set[str], suspicious: bool) -> str:
    if suspicious:
        return "suspicious"
    normalized_groups = {group.removeprefix("official:") for group in groups}
    if any(is_official(group) for group in groups) or (len(normalized_groups) >= 2 and any(not group.startswith("x:") for group in normalized_groups)):
        return "verified"
    return "pending"


class Monitor:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.sources = SourceCollector(settings.twitterapi_key)
        self.judge = OpenRouterJudge(settings.openrouter_api_key, settings.openrouter_model)
        self._locks: dict[int, asyncio.Lock] = {}
        self._loop_task: asyncio.Task | None = None

    def start(self) -> None:
        if self.settings.scheduler_enabled:
            self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while True:
            try:
                with self.db.connect() as connection:
                    rules = [dict(row) for row in connection.execute("SELECT * FROM rules WHERE enabled=1")]
                for rule in rules:
                    if self._is_due(rule):
                        await self.scan_rule(rule["id"])
                await self.retry_emails()
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单次循环失败不应使持续监控永久停止。
                pass
            await asyncio.sleep(30)

    @staticmethod
    def _is_due(rule: dict) -> bool:
        if not rule["last_run_at"]:
            return True
        last = datetime.fromisoformat(rule["last_run_at"])
        return (datetime.now(timezone.utc) - last).total_seconds() >= rule["interval_minutes"] * 60

    def _source_due(self, rule_id: int, source: str, minutes: int) -> bool:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT checked_at, error FROM source_runs WHERE rule_id=? AND source=? ORDER BY id DESC LIMIT 1",
                (rule_id, source),
            ).fetchone()
        if not row:
            return True
        wait_minutes = min(minutes * 2, 60) if row["error"] else minutes
        return (datetime.now(timezone.utc) - datetime.fromisoformat(row["checked_at"])).total_seconds() >= wait_minutes * 60

    async def scan_rule(self, rule_id: int, force: bool = False, per_source_limit: int = 4) -> dict:
        lock = self._locks.setdefault(rule_id, asyncio.Lock())
        if lock.locked():
            return {"status": "busy", "message": "该监控项正在扫描"}
        async with lock:
            with self.db.connect() as connection:
                row = connection.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
                if not row:
                    raise ValueError("监控项不存在")
                rule = dict(row)
            if not self.settings.openrouter_api_key:
                error = "尚未配置 OPENROUTER_API_KEY，无法进行 AI 核实"
                self._save_rule_error(rule_id, error)
                return {"status": "error", "message": error, "new_events": 0}

            sources = [
                ("google_news", self.sources.google_news, 5),
                ("bing", self.sources.bing, 15),
                ("official_rss", lambda _query: self.sources.official_rss(self.settings.official_rss_urls), 30),
                ("twitter", self.sources.twitter, 5),
            ]
            tasks = [(name, method(rule["query"])) for name, method, minutes in sources if force or self._source_due(rule_id, name, minutes)]
            results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
            all_candidates: list[Candidate] = []
            errors: list[str] = []
            for (name, _), result in zip(tasks, results):
                if isinstance(result, BaseException):
                    errors.append(f"{name}: {result}")
                    count = 0
                else:
                    all_candidates.extend(result[:per_source_limit])
                    count = len(result)
                with self.db.connect() as connection:
                    connection.execute(
                        "INSERT INTO source_runs(rule_id, source, checked_at, result_count, error) VALUES(?,?,?,?,?)",
                        (rule_id, name, utc_now(), count, str(result)[:300] if isinstance(result, BaseException) else None),
                    )

            new_events = 0
            for candidate in all_candidates:
                with self.db.connect() as connection:
                    known = connection.execute(
                        "SELECT 1 FROM evidence e JOIN events v ON v.id=e.event_id WHERE v.rule_id=? AND e.source_url=?",
                        (rule_id, candidate.url),
                    ).fetchone()
                    recent = [dict(row) for row in connection.execute(
                        "SELECT id, title, summary FROM events WHERE rule_id=? ORDER BY updated_at DESC LIMIT 20",
                        (rule_id,),
                    )]
                if known:
                    continue
                try:
                    judgment = await self.judge.judge(rule["query"], rule["kind"], candidate, recent)
                except Exception as exc:
                    errors.append(f"AI 判读失败: {exc}")
                    break
                if not judgment.relevant:
                    continue
                created = self._save_candidate(rule, candidate, judgment)
                new_events += int(created)

            self._save_rule_error(rule_id, "；".join(errors)[:800] if errors else None)
            return {"status": "partial" if errors else "ok", "message": "；".join(errors) if errors else "扫描完成", "new_events": new_events}

    def _save_rule_error(self, rule_id: int, error: str | None) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE rules SET last_run_at=?, last_error=? WHERE id=?",
                (utc_now(), error, rule_id),
            )

    def _save_candidate(self, rule: dict, candidate: Candidate, judgment: Judgment) -> bool:
        now = utc_now()
        with self.db.connect() as connection:
            matched = judgment.matched_event_id
            existing = connection.execute("SELECT * FROM events WHERE id=? AND rule_id=?", (matched, rule["id"])).fetchone() if matched else None
            if existing:
                event_id = existing["id"]
                connection.execute(
                    "UPDATE events SET updated_at=?, heat=MAX(heat, ?), summary=?, reason=? WHERE id=?",
                    (now, judgment.heat, judgment.summary, judgment.reason, event_id),
                )
            else:
                cursor = connection.execute(
                    "INSERT INTO events(rule_id,title,summary,reason,status,relevance,heat,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (rule["id"], candidate.title, judgment.summary, judgment.reason, "pending", 1, judgment.heat, now, now),
                )
                event_id = cursor.lastrowid
            connection.execute(
                "INSERT OR IGNORE INTO evidence(event_id,source,source_group,source_url,title,snippet,suspicious,published_at,found_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, candidate.source, candidate.source_group, candidate.url, candidate.title, candidate.snippet, int(judgment.suspicious), candidate.published_at, now),
            )
            groups = {row["source_group"] for row in connection.execute("SELECT source_group FROM evidence WHERE event_id=? AND suspicious=0", (event_id,))}
            suspicious = not groups
            status = status_for_evidence(groups, suspicious)
            connection.execute("UPDATE events SET status=? WHERE id=?", (status, event_id))
            if rule["kind"] == "keyword" and status == "verified":
                connection.execute(
                    "INSERT OR IGNORE INTO notifications(event_id,created_at,email_status) VALUES(?,?,?)",
                    (event_id, now, "待发送" if self._mail_ready() else "待配置"),
                )
        return existing is None

    def _mail_ready(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_from and self.settings.alert_email)

    async def retry_emails(self) -> None:
        if not self._mail_ready():
            return
        with self.db.connect() as connection:
            pending = [dict(row) for row in connection.execute(
                "SELECT n.id, e.title, e.summary, e.id AS event_id FROM notifications n "
                "JOIN events e ON e.id=n.event_id WHERE n.email_status IN ('待发送','待配置','失败') "
                "AND (n.last_attempt_at IS NULL OR datetime(n.last_attempt_at) <= datetime('now','-5 minutes')) LIMIT 10"
            )]
        for item in pending:
            try:
                await asyncio.to_thread(self._send_email, item)
                status, error = "已发送", None
            except Exception as exc:
                status, error = "失败", str(exc)[:300]
            with self.db.connect() as connection:
                connection.execute(
                    "UPDATE notifications SET email_status=?, email_error=?, last_attempt_at=? WHERE id=?",
                    (status, error, utc_now(), item["id"]),
                )
                if status == "已发送":
                    connection.execute("UPDATE events SET notified_at=? WHERE id=?", (utc_now(), item["event_id"]))

    def _send_email(self, item: dict) -> None:
        message = EmailMessage()
        message["Subject"] = f"[热点监控] {item['title'][:80]}"
        message["From"] = self.settings.smtp_from
        message["To"] = self.settings.alert_email
        message.set_content(f"{item['summary']}\n\n请打开本机热点监控网页查看来源与核实依据。")
        smtp_class = smtplib.SMTP_SSL if self.settings.smtp_ssl or self.settings.smtp_port == 465 else smtplib.SMTP
        with smtp_class(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            if self.settings.smtp_starttls and smtp_class is smtplib.SMTP:
                smtp.starttls()
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(message)
