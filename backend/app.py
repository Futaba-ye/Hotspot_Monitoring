from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import ROOT, Settings, get_settings
from .db import Database, rows_to_dict
from .monitor import Monitor, utc_now


class RuleCreate(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    kind: Literal["keyword", "topic"]
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class RuleUpdate(BaseModel):
    query: str | None = Field(default=None, min_length=2, max_length=120)
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    database = Database(config.database_path)
    monitor = Monitor(database, config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        monitor.start()
        yield
        await monitor.stop()

    app = FastAPI(title="热点监控", lifespan=lifespan)
    app.state.database = database
    app.state.monitor = monitor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/status")
    def status():
        with database.connect() as connection:
            rules = connection.execute("SELECT COUNT(*) AS n FROM rules WHERE enabled=1").fetchone()["n"]
            events = connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            unread = connection.execute("SELECT COUNT(*) AS n FROM notifications WHERE read_at IS NULL").fetchone()["n"]
            sources = rows_to_dict(connection.execute(
                "SELECT s.source,s.checked_at,s.result_count,s.error FROM source_runs s "
                "JOIN (SELECT source, MAX(id) AS id FROM source_runs GROUP BY source) latest ON latest.id=s.id"
            ).fetchall())
        return {
            "rules": rules, "events": events, "unread": unread,
            "ai_configured": bool(config.openrouter_api_key),
            "x_configured": bool(config.twitterapi_key),
            "email_configured": bool(config.smtp_host and config.smtp_from and config.alert_email),
            "model": config.openrouter_model,
            "sources": sources,
        }

    @app.get("/api/rules")
    def list_rules():
        with database.connect() as connection:
            return rows_to_dict(connection.execute("SELECT * FROM rules ORDER BY created_at DESC, id DESC").fetchall())

    @app.post("/api/rules", status_code=201)
    def create_rule(body: RuleCreate):
        query = body.query.strip()
        if len(query) < 2:
            raise HTTPException(422, "监控内容至少需要两个字符")
        interval = body.interval_minutes or (5 if body.kind == "keyword" else 30)
        with database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO rules(query,kind,interval_minutes,created_at) VALUES(?,?,?,?)",
                (query, body.kind, interval, utc_now()),
            )
            row = connection.execute("SELECT * FROM rules WHERE id=?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    @app.patch("/api/rules/{rule_id}")
    def update_rule(rule_id: int, body: RuleUpdate):
        values = body.model_dump(exclude_unset=True)
        if "query" in values:
            if values["query"] is None:
                raise HTTPException(422, "监控内容不能为空")
            values["query"] = values["query"].strip()
            if len(values["query"]) < 2:
                raise HTTPException(422, "监控内容至少需要两个字符")
        if "interval_minutes" in values and values["interval_minutes"] is None:
            raise HTTPException(422, "扫描周期不能为空")
        if "enabled" in values and values["enabled"] is None:
            raise HTTPException(422, "启停状态不能为空")
        if "enabled" in values:
            values["enabled"] = int(values["enabled"])
        if not values:
            raise HTTPException(422, "没有需要更新的字段")
        with database.connect() as connection:
            row = connection.execute("SELECT id FROM rules WHERE id=?", (rule_id,)).fetchone()
            if not row:
                raise HTTPException(404, "监控项不存在")
            fields = ", ".join(f"{field}=?" for field in values)
            connection.execute(f"UPDATE rules SET {fields} WHERE id=?", (*values.values(), rule_id))
            updated = connection.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        return dict(updated)

    @app.delete("/api/rules/{rule_id}", status_code=204)
    def delete_rule(rule_id: int):
        with database.connect() as connection:
            cursor = connection.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            if cursor.rowcount == 0:
                raise HTTPException(404, "监控项不存在")

    @app.post("/api/rules/{rule_id}/scan")
    async def scan_rule(rule_id: int):
        try:
            return await monitor.scan_rule(rule_id, force=True)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/events")
    def list_events(rule_id: int | None = None, status: Literal["verified", "pending", "suspicious"] | None = None):
        clauses: list[str] = []
        values: list[object] = []
        if rule_id is not None:
            clauses.append("v.rule_id=?")
            values.append(rule_id)
        if status:
            clauses.append("v.status=?")
            values.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with database.connect() as connection:
            events = rows_to_dict(connection.execute(
                f"SELECT v.*,r.query AS rule_query,r.kind AS rule_kind FROM events v "
                f"JOIN rules r ON r.id=v.rule_id {where} ORDER BY v.updated_at DESC LIMIT 100", values,
            ).fetchall())
            for event in events:
                event["evidence"] = rows_to_dict(connection.execute(
                    "SELECT source,source_group,source_url,title,snippet,published_at,found_at "
                    "FROM evidence WHERE event_id=? ORDER BY id DESC", (event["id"],),
                ).fetchall())
        return events

    @app.get("/api/notifications")
    def list_notifications():
        with database.connect() as connection:
            return rows_to_dict(connection.execute(
                "SELECT n.*,e.title,e.summary,e.rule_id FROM notifications n "
                "JOIN events e ON e.id=n.event_id ORDER BY n.created_at DESC LIMIT 100"
            ).fetchall())

    @app.post("/api/notifications/{notification_id}/read")
    def read_notification(notification_id: int):
        with database.connect() as connection:
            cursor = connection.execute("UPDATE notifications SET read_at=? WHERE id=?", (utc_now(), notification_id))
            if cursor.rowcount == 0:
                raise HTTPException(404, "提醒不存在")
        return {"ok": True}

    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "接口不存在")
            target = (frontend_dist / path).resolve()
            if target.is_file() and target.is_relative_to(frontend_dist.resolve()):
                return FileResponse(target)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()
