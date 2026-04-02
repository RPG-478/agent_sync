"""agent_sync.client_v6 — Flat 2-agent CLI client.

Commands: join, status, peek, send, broadcast, listen,
          impl-done, test-result, discuss, discuss-done,
          get-discussion, say, write-log, set-phase, heartbeat, shutdown
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _request(msg: dict, host: str = "127.0.0.1", port: int = 9800,
                   timeout: float | None = None,
                   retry: bool = True, retry_interval: float = 3.0,
                   max_retries: int = 60) -> dict:
    attempts = 0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            break
        except (ConnectionRefusedError, OSError) as e:
            attempts += 1
            if not retry or attempts >= max_retries:
                return {"ok": False, "error": f"cannot connect ({e})"}
            print(f"[agent_sync] Waiting for server on port {port}... ({attempts})",
                  file=sys.stderr, flush=True)
            await asyncio.sleep(retry_interval)

    try:
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()
        if timeout:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout + 5)
        else:
            line = await reader.readline()
        if not line:
            return {"ok": False, "error": "connection closed"}
        return json.loads(line.decode().strip())
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _print(resp: dict) -> int:
    if resp.get("ok"):
        data = {k: v for k, v in resp.items() if k != "ok"}
        if data:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("OK")
        return 0
    else:
        print(f"ERROR: {resp.get('error', 'unknown')}", file=sys.stderr)
        return 1


# ━━━ Command functions (importable) ━━━━━━━━━━

async def cmd_join(agent: str, port: int) -> int:
    return _print(await _request({"cmd": "join", "agent": agent}, port=port))

async def cmd_status(port: int) -> int:
    return _print(await _request({"cmd": "status"}, port=port))

async def cmd_peek(agent: str, port: int) -> int:
    return _print(await _request({"cmd": "peek", "agent": agent}, port=port,
                                  retry=False))

async def cmd_send(from_: str, to: str, text: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "send", "agent": from_, "to": to, "text": text}, port=port))

async def cmd_broadcast(from_: str, text: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "broadcast", "agent": from_, "text": text}, port=port))

async def cmd_listen(agent: str, timeout: int, port: int) -> int:
    return _print(await _request(
        {"cmd": "listen", "agent": agent, "timeout": timeout},
        port=port, timeout=timeout))

async def cmd_impl_done(agent: str, summary: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "impl-done", "agent": agent, "summary": summary}, port=port))

async def cmd_test_result(agent: str, passed: bool, output: str,
                          failures: list, port: int) -> int:
    return _print(await _request(
        {"cmd": "test-result", "agent": agent, "passed": passed,
         "output": output, "failures": failures}, port=port))

async def cmd_discuss(agent: str, text: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "discuss", "agent": agent, "text": text}, port=port))

async def cmd_discuss_done(agent: str, next_impl: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "discuss-done", "agent": agent,
         "next_implementer": next_impl}, port=port))

async def cmd_get_discussion(port: int, round_num: int | None = None) -> int:
    msg: dict = {"cmd": "get-discussion"}
    if round_num is not None:
        msg["round"] = round_num
    return _print(await _request(msg, port=port))

async def cmd_say(text: str, to: str | None, port: int) -> int:
    msg: dict = {"cmd": "say", "text": text}
    if to:
        msg["to"] = to
    return _print(await _request(msg, port=port))

async def cmd_write_log(agent: str, text: str, section: str, port: int) -> int:
    return _print(await _request(
        {"cmd": "write-log", "agent": agent, "text": text, "section": section}, port=port))

async def cmd_set_phase(phase: str, port: int) -> int:
    return _print(await _request({"cmd": "set-phase", "phase": phase}, port=port))

async def cmd_heartbeat(agent: str, port: int) -> int:
    return _print(await _request({"cmd": "heartbeat", "agent": agent}, port=port))

async def cmd_shutdown(reason: str, port: int) -> int:
    return _print(await _request({"cmd": "shutdown", "reason": reason}, port=port))


async def cmd_check_notify(agent: str) -> int:
    """Check notifications written by the background notifier."""
    from agent_sync.notifier import check_notifications
    notifications = check_notifications(agent)
    if not notifications:
        print(json.dumps({"notifications": [], "count": 0}, ensure_ascii=False))
        return 0
    print(json.dumps({"notifications": notifications, "count": len(notifications)},
                      ensure_ascii=False, indent=2))
    return 0


async def cmd_clear_notify(agent: str) -> int:
    """Clear all notifications for the agent."""
    from agent_sync.notifier import clear_notifications
    clear_notifications(agent)
    print("OK")
    return 0


# ━━━ CLI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _port(p):
    p.add_argument("--port", type=int, default=9800)

def cli():
    p = argparse.ArgumentParser(prog="client_v6", description="agent_sync v6 CLI")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("join"); s.add_argument("agent"); _port(s)
    s = sub.add_parser("status"); _port(s)
    s = sub.add_parser("peek"); s.add_argument("agent"); _port(s)
    s = sub.add_parser("send"); s.add_argument("from_agent"); s.add_argument("to_agent"); s.add_argument("message"); _port(s)
    s = sub.add_parser("broadcast"); s.add_argument("from_agent"); s.add_argument("message"); _port(s)
    s = sub.add_parser("listen"); s.add_argument("agent"); s.add_argument("--timeout", type=int, default=300); _port(s)
    s = sub.add_parser("impl-done"); s.add_argument("agent"); s.add_argument("--summary", default=""); _port(s)
    s = sub.add_parser("test-result"); s.add_argument("agent"); s.add_argument("--passed", action="store_true"); s.add_argument("--output", default=""); s.add_argument("--failures", nargs="*", default=[]); _port(s)
    s = sub.add_parser("discuss"); s.add_argument("agent"); s.add_argument("text"); _port(s)
    s = sub.add_parser("discuss-done"); s.add_argument("agent"); s.add_argument("--next-impl", default=""); _port(s)
    s = sub.add_parser("get-discussion"); s.add_argument("--round", type=int, default=None); _port(s)
    s = sub.add_parser("say"); s.add_argument("text"); s.add_argument("--to", default=None); _port(s)
    s = sub.add_parser("write-log"); s.add_argument("agent"); s.add_argument("text"); s.add_argument("--section", default=""); _port(s)
    s = sub.add_parser("set-phase"); s.add_argument("phase", choices=["IMPLEMENT","TEST","DISCUSS","SHUTDOWN"]); _port(s)
    s = sub.add_parser("heartbeat"); s.add_argument("agent"); _port(s)
    s = sub.add_parser("shutdown"); s.add_argument("--reason", default="completed"); _port(s)
    s = sub.add_parser("check-notify"); s.add_argument("agent")
    s = sub.add_parser("clear-notify"); s.add_argument("agent")

    args = p.parse_args()
    if not args.command:
        p.print_help(); return 1

    port = args.port
    coro = {
        "join":           lambda: cmd_join(args.agent, port),
        "status":         lambda: cmd_status(port),
        "peek":           lambda: cmd_peek(args.agent, port),
        "send":           lambda: cmd_send(args.from_agent, args.to_agent, args.message, port),
        "broadcast":      lambda: cmd_broadcast(args.from_agent, args.message, port),
        "listen":         lambda: cmd_listen(args.agent, args.timeout, port),
        "impl-done":      lambda: cmd_impl_done(args.agent, args.summary, port),
        "test-result":    lambda: cmd_test_result(args.agent, args.passed, args.output, args.failures, port),
        "discuss":        lambda: cmd_discuss(args.agent, args.text, port),
        "discuss-done":   lambda: cmd_discuss_done(args.agent, args.next_impl, port),
        "get-discussion": lambda: cmd_get_discussion(port, args.round),
        "say":            lambda: cmd_say(args.text, args.to, port),
        "write-log":      lambda: cmd_write_log(args.agent, args.text, args.section, port),
        "set-phase":      lambda: cmd_set_phase(args.phase, port),
        "heartbeat":      lambda: cmd_heartbeat(args.agent, port),
        "shutdown":       lambda: cmd_shutdown(args.reason, port),
        "check-notify":  lambda: cmd_check_notify(args.agent),
        "clear-notify":  lambda: cmd_clear_notify(args.agent),
    }.get(args.command)

    if coro is None:
        p.print_help(); return 1
    return asyncio.run(coro())


if __name__ == "__main__":
    sys.exit(cli())
