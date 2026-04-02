"""agent_sync.server_v6 — Flat N-agent TCP server. No branches, no MERGE phase.

Agents: configurable via AGENTS_LIST env var (default: agent-a,agent-b).
Phase cycle: IMPLEMENT → TEST → DISCUSS → IMPLEMENT (round+1)
PostToolUse-friendly: peek command for non-blocking message check.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [v6] %(message)s")
log = logging.getLogger("agent_sync.v6")

_agents_raw = os.environ.get("AGENTS_LIST", "agent-a,agent-b")
AGENTS = tuple(a.strip() for a in _agents_raw.split(",") if a.strip())
PHASES = ("IMPLEMENT", "TEST", "DISCUSS", "SHUTDOWN")


@dataclass
class ServerState:
    phase: str = "IMPLEMENT"
    round_number: int = 1
    log_dir: str = "logs/v6"

    # Agent tracking
    agents: dict[str, dict] = field(default_factory=dict)

    # Mailboxes: agent_name -> [msg, ...]
    mailboxes: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    mail_events: dict[str, asyncio.Event] = field(default_factory=dict)

    # Who is implementing this round (set during DISCUSS or first join)
    implementer: str = ""

    # Discuss-done tracking
    discuss_done: set = field(default_factory=set)

    # Discussion log (all rounds)
    discussion: list[dict] = field(default_factory=list)

    # Latest test result
    test_result: dict | None = None


S = ServerState()


# ━━━ Utilities ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _reply(ok: bool, **kw) -> dict:
    return {"ok": ok, **kw}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _broadcast(msg_type: str, text: str, exclude: str = "") -> None:
    for name in list(S.agents.keys()):
        if name == exclude:
            continue
        S.mailboxes[name].append({
            "from": "__server__", "type": msg_type,
            "text": text, "ts": time.time(),
        })
        evt = S.mail_events.get(name)
        if evt:
            evt.set()


def _set_phase(new_phase: str) -> None:
    old = S.phase
    S.phase = new_phase
    log.info("Phase: %s → %s (round %d)", old, new_phase, S.round_number)
    _broadcast("phase_change",
               f"Phase changed: {old} -> {new_phase} (round {S.round_number})")


def _write_log(section: str, agent: str, text: str) -> str:
    Path(S.log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(S.log_dir) / f"round_{S.round_number}.md"
    entry = f"\n## {section} / {agent} — {_now()}\n\n{text}\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)
    return str(log_file)


# ━━━ Handlers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def handle_join(msg: dict) -> dict:
    name = msg.get("agent", "")
    if name not in AGENTS:
        return _reply(False, error=f"Invalid agent name. Must be one of: {AGENTS}")
    S.agents[name] = {
        "status": "idle", "joined_at": time.time(),
    }
    if name not in S.mail_events:
        S.mail_events[name] = asyncio.Event()
    # First agent to join becomes default implementer
    if not S.implementer:
        S.implementer = name
    log.info("Agent joined: %s (total: %d)", name, len(S.agents))
    return _reply(True, message=f"Joined as {name}",
                  phase=S.phase, round=S.round_number,
                  implementer=S.implementer)


def handle_status(msg: dict) -> dict:
    return _reply(True, data={
        "phase": S.phase,
        "round": S.round_number,
        "agents": {n: info for n, info in S.agents.items()},
        "implementer": S.implementer,
        "discuss_done": list(S.discuss_done),
        "test_result": S.test_result,
    })


def handle_peek(msg: dict) -> dict:
    """Non-blocking check for pending messages. Used by hooks."""
    name = msg.get("agent", "")
    count = len(S.mailboxes.get(name, []))
    return _reply(True, pending=count, phase=S.phase,
                  round=S.round_number, implementer=S.implementer)


def handle_send(msg: dict) -> dict:
    to = msg.get("to", "")
    if to not in AGENTS:
        return _reply(False, error=f"Unknown target: {to}")
    payload = {
        "from": msg.get("agent", "user"),
        "type": msg.get("msg_type", "message"),
        "text": msg.get("text", ""),
        "ts": time.time(),
    }
    S.mailboxes[to].append(payload)
    evt = S.mail_events.get(to)
    if evt:
        evt.set()
    return _reply(True)


def handle_broadcast(msg: dict) -> dict:
    text = msg.get("text", "")
    sender = msg.get("agent", "user")
    for name in list(S.agents.keys()):
        if name == sender:
            continue  # do not echo back to sender
        S.mailboxes[name].append({
            "from": sender, "type": "broadcast",
            "text": text, "ts": time.time(),
        })
        evt = S.mail_events.get(name)
        if evt:
            evt.set()
    return _reply(True)


async def handle_listen(msg: dict) -> dict:
    name = msg.get("agent", "")
    timeout = msg.get("timeout", 60)

    if S.mailboxes[name]:
        msgs = list(S.mailboxes[name])
        S.mailboxes[name].clear()
        return _reply(True, messages=msgs)

    if name not in S.mail_events:
        S.mail_events[name] = asyncio.Event()
    S.mail_events[name].clear()

    try:
        await asyncio.wait_for(S.mail_events[name].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass

    msgs = list(S.mailboxes[name])
    S.mailboxes[name].clear()
    return _reply(True, messages=msgs, timeout=len(msgs) == 0)


def handle_impl_done(msg: dict) -> dict:
    """Implementer signals code is done → IMPLEMENT → TEST."""
    name = msg.get("agent", "")
    summary = msg.get("summary", "")
    if S.phase != "IMPLEMENT":
        return _reply(False, error=f"Not in IMPLEMENT phase (current: {S.phase})")
    if S.implementer and name != S.implementer:
        return _reply(False, error=f"Only the implementer ({S.implementer}) can call impl-done")
    _write_log("IMPL_DONE", name, summary)
    _set_phase("TEST")
    return _reply(True, phase=S.phase)


def handle_test_result(msg: dict) -> dict:
    """Tester reports results → TEST → DISCUSS."""
    S.test_result = {
        "agent": msg.get("agent", ""),
        "passed": msg.get("passed", False),
        "output": msg.get("output", ""),
        "failures": msg.get("failures", []),
        "ts": time.time(),
    }
    _write_log("TEST_RESULT", msg.get("agent", ""),
               f"passed={S.test_result['passed']}\n\n{S.test_result['output']}")
    if S.phase == "TEST":
        S.discuss_done.clear()
        _set_phase("DISCUSS")
    return _reply(True, passed=S.test_result["passed"])


def handle_discuss(msg: dict) -> dict:
    """Post a discussion message → forwarded to the other agent."""
    if S.phase != "DISCUSS":
        return _reply(False, error=f"Not in DISCUSS phase (current: {S.phase})")
    entry = {
        "agent": msg.get("agent", ""),
        "text": msg.get("text", ""),
        "round": S.round_number,
        "ts": time.time(),
    }
    S.discussion.append(entry)
    sender = msg.get("agent", "")
    for name in AGENTS:
        if name != sender and name in S.agents:
            S.mailboxes[name].append({
                "from": sender, "type": "discuss",
                "text": msg.get("text", ""), "ts": time.time(),
            })
            evt = S.mail_events.get(name)
            if evt:
                evt.set()
    return _reply(True, round=S.round_number)


def handle_discuss_done(msg: dict) -> dict:
    """Agent signals done discussing. When both done → IMPLEMENT round+1."""
    if S.phase != "DISCUSS":
        return _reply(False, error=f"Not in DISCUSS phase (current: {S.phase})")
    name = msg.get("agent", "")
    next_implementer = msg.get("next_implementer", "")
    S.discuss_done.add(name)
    log.info("discuss-done: %s (%d/%d)", name, len(S.discuss_done), len(AGENTS))

    if len(S.discuss_done) >= len(AGENTS) and S.phase == "DISCUSS":
        S.round_number += 1
        S.discuss_done.clear()
        S.test_result = None
        if next_implementer and next_implementer in AGENTS:
            S.implementer = next_implementer
        _set_phase("IMPLEMENT")

    return _reply(True, discuss_done=list(S.discuss_done),
                  round=S.round_number, implementer=S.implementer)


def handle_get_discussion(msg: dict) -> dict:
    round_filter = msg.get("round", None)
    if round_filter is not None:
        filtered = [d for d in S.discussion if d["round"] == round_filter]
        return _reply(True, discussion=filtered)
    return _reply(True, discussion=S.discussion)


def handle_say(msg: dict) -> dict:
    """User intervention: DM or broadcast."""
    to = msg.get("to", "")
    text = msg.get("text", "")
    if to:
        S.mailboxes[to].append({
            "from": "user", "type": "say",
            "text": text, "ts": time.time(),
        })
        evt = S.mail_events.get(to)
        if evt:
            evt.set()
        log.info("User say → %s: %s", to, text[:80])
    else:
        for name in list(S.agents.keys()):
            S.mailboxes[name].append({
                "from": "user", "type": "say",
                "text": text, "ts": time.time(),
            })
            evt = S.mail_events.get(name)
            if evt:
                evt.set()
        log.info("User say (broadcast): %s", text[:80])
    return _reply(True)


def handle_write_log(msg: dict) -> dict:
    section = msg.get("section", S.phase)
    agent = msg.get("agent", "unknown")
    text = msg.get("text", "")
    path = _write_log(section, agent, text)
    return _reply(True, log_file=path)


def handle_set_phase(msg: dict) -> dict:
    phase = msg.get("phase", "")
    if phase not in PHASES:
        return _reply(False, error=f"Invalid phase. Must be one of: {PHASES}")
    _set_phase(phase)
    return _reply(True, phase=S.phase, round=S.round_number)


def handle_shutdown(msg: dict) -> dict:
    reason = msg.get("reason", "manual")
    log.info("SHUTDOWN requested: %s", reason)
    _set_phase("SHUTDOWN")
    return _reply(True, message="Shutting down", reason=reason)


def handle_heartbeat(msg: dict) -> dict:
    name = msg.get("agent", "")
    if name in S.agents:
        S.agents[name]["last_heartbeat"] = time.time()
    return _reply(True, phase=S.phase, round=S.round_number)


# ━━━ Dispatch ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HANDLERS: dict[str, Any] = {
    "join": handle_join,
    "status": handle_status,
    "peek": handle_peek,
    "send": handle_send,
    "broadcast": handle_broadcast,
    "listen": handle_listen,
    "impl-done": handle_impl_done,
    "test-result": handle_test_result,
    "discuss": handle_discuss,
    "discuss-done": handle_discuss_done,
    "get-discussion": handle_get_discussion,
    "say": handle_say,
    "write-log": handle_write_log,
    "set-phase": handle_set_phase,
    "shutdown": handle_shutdown,
    "heartbeat": handle_heartbeat,
}

ASYNC_HANDLERS = {"listen"}


async def dispatch(msg: dict) -> dict:
    cmd = msg.get("cmd", "")
    handler = HANDLERS.get(cmd)
    if handler is None:
        return _reply(False, error=f"Unknown command: {cmd}")
    try:
        if cmd in ASYNC_HANDLERS:
            return await handler(msg)
        return handler(msg)
    except Exception as e:
        log.error("Handler error [%s]: %s", cmd, e, exc_info=True)
        return _reply(False, error=str(e))


# ━━━ TCP Server ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_client(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                reply = _reply(False, error="Invalid JSON")
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
                continue
            reply = await dispatch(msg)
            writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def run_server(host: str = "127.0.0.1", port: int = 9800):
    server = await asyncio.start_server(handle_client, host, port)
    log.info("v6 flat N-agent server on %s:%d", host, port)
    log.info("Phases: %s  Agents: %s", PHASES, AGENTS)
    async with server:
        await server.serve_forever()


def main():
    p = argparse.ArgumentParser(description="agent_sync v6 server (flat N-agent, no branches)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9800)
    args = p.parse_args()
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
