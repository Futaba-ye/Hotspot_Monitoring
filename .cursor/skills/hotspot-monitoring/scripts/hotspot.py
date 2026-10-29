from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.getenv("HOTSPOT_MONITOR_URL", "http://127.0.0.1:8000").rstrip("/")


def request(path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    operation = Request(BASE_URL + "/api" + path, data=data, headers=headers, method=method)
    try:
        with urlopen(operation, timeout=180 if path.endswith("/scan") else 20) as response:
            body = response.read()
            return json.loads(body) if body else {"ok": True}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except (ValueError, UnicodeDecodeError):
            detail = ""
        raise RuntimeError(f"接口返回 HTTP {exc.code}：{detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接热点监控服务：{exc.reason}") from exc


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="管理脉冲台热点监控")
    sub = command.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="查看服务与连接状态")
    sub.add_parser("rules", help="列出监控任务")
    sub.add_parser("alerts", help="列出提醒")
    add = sub.add_parser("add", help="创建监控任务")
    add.add_argument("query", help="关键词或领域")
    add.add_argument("--kind", choices=("keyword", "topic"), required=True)
    add.add_argument("--interval", type=int, help="扫描周期，单位为分钟")
    update = sub.add_parser("update", help="修改监控任务")
    update.add_argument("id", type=int)
    update.add_argument("--query")
    update.add_argument("--interval", type=int)
    state = update.add_mutually_exclusive_group()
    state.add_argument("--pause", action="store_true")
    state.add_argument("--resume", action="store_true")
    delete = sub.add_parser("delete", help="删除监控任务及历史结果")
    delete.add_argument("id", type=int)
    scan = sub.add_parser("scan", help="立即扫描监控任务")
    scan.add_argument("id", type=int)
    events = sub.add_parser("events", help="列出热点事件及证据")
    events.add_argument("--rule-id", type=int)
    events.add_argument("--status", choices=("verified", "pending", "suspicious"))
    read = sub.add_parser("read", help="将提醒标记为已读")
    read.add_argument("id", type=int)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.action == "status":
            result = request("/status")
        elif args.action == "rules":
            result = request("/rules")
        elif args.action == "alerts":
            result = request("/notifications")
        elif args.action == "add":
            payload = {"query": args.query, "kind": args.kind}
            if args.interval is not None:
                payload["interval_minutes"] = args.interval
            result = request("/rules", "POST", payload)
        elif args.action == "update":
            payload = {}
            if args.query is not None:
                payload["query"] = args.query
            if args.interval is not None:
                payload["interval_minutes"] = args.interval
            if args.pause:
                payload["enabled"] = False
            if args.resume:
                payload["enabled"] = True
            if not payload:
                raise RuntimeError("请提供要修改的内容")
            result = request(f"/rules/{args.id}", "PATCH", payload)
        elif args.action == "delete":
            result = request(f"/rules/{args.id}", "DELETE")
        elif args.action == "scan":
            result = request(f"/rules/{args.id}/scan", "POST")
        elif args.action == "events":
            params = {}
            if args.rule_id is not None:
                params["rule_id"] = args.rule_id
            if args.status:
                params["status"] = args.status
            suffix = "?" + urlencode(params) if params else ""
            result = request("/events" + suffix)
        else:
            result = request(f"/notifications/{args.id}/read", "POST")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
