#!/usr/bin/env python3
"""agent_sync v6 Notifier — Background notification watcher.

Runs in a background terminal, polls for messages via peek/listen,
and writes notifications to a shared file that agents can check.

Usage:
    python agent_sync/notifier.py agent-b [--port 9800] [--interval 5]

The notifier writes to:
    agent_sync/.notifications_{agent}.jsonl   (append-only, one JSON per line)
    agent_sync/.notify_bell_{agent}           (touch file — presence = unread)

Agents should:
    1. Check for .notify_bell_{agent} file existence (fast)
    2. If exists, read .notifications_{agent}.jsonl
    3. Delete .notify_bell_{agent} after reading (acknowledge)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent


async def tcp_cmd(cmd: dict, port: int, timeout: float = 5) -> dict | None:
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write((json.dumps(cmd) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        writer.close()
        if line:
            return json.loads(line.decode().strip())
    except Exception:
        pass
    return None


async def run_notifier(agent: str, port: int, interval: float):
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"
    last_phase = ""
    last_round = 0

    print(f"[notifier] Watching for {agent} on port {port} (interval={interval}s)")
    print(f"[notifier] Notifications → {notif_file}")
    print(f"[notifier] Bell file    → {bell_file}")

    while True:
        try:
            # 1. Check status for phase changes
            status = await tcp_cmd({"cmd": "status"}, port)
            if status and status.get("ok"):
                data = status.get("data", {})
                phase = data.get("phase", "")
                rnd = data.get("round", 0)

                if phase != last_phase or rnd != last_round:
                    if last_phase:  # Don't notify on first poll
                        _write_notification(notif_file, bell_file, {
                            "type": "phase_change",
                            "from_phase": last_phase,
                            "to_phase": phase,
                            "round": rnd,
                            "ts": time.time(),
                        })
                        print(f"[notifier] Phase: {last_phase} → {phase} (round {rnd})")
                    last_phase = phase
                    last_round = rnd

                # Detect SHUTDOWN
                if phase == "SHUTDOWN":
                    _write_notification(notif_file, bell_file, {
                        "type": "shutdown",
                        "ts": time.time(),
                    })
                    print("[notifier] SHUTDOWN detected, exiting.")
                    return

            # 2. Peek for messages (non-blocking)
            peek = await tcp_cmd({"cmd": "peek", "agent": agent}, port)
            if peek and peek.get("ok"):
                count = peek.get("count", 0)
                if count > 0:
                    # Fetch messages with short listen
                    resp = await tcp_cmd(
                        {"cmd": "listen", "agent": agent, "timeout": 2},
                        port, timeout=5,
                    )
                    if resp and resp.get("ok"):
                        messages = resp.get("messages", [])
                        for msg in messages:
                            _write_notification(notif_file, bell_file, {
                                "type": "message",
                                "from": msg.get("from", "?"),
                                "msg_type": msg.get("type", "?"),
                                "text": msg.get("text", "")[:200],
                                "ts": msg.get("ts", time.time()),
                            })
                            sender = msg.get("from", "?")
                            mtype = msg.get("type", "?")
                            print(f"[notifier] Message from {sender} ({mtype})")

            # 3. Send heartbeat
            await tcp_cmd({"cmd": "heartbeat", "agent": agent}, port)

        except Exception as e:
            print(f"[notifier] Error: {e}", file=sys.stderr)

        await asyncio.sleep(interval)


def _write_notification(notif_file: Path, bell_file: Path, data: dict):
    """Append notification and touch bell file."""
    with open(notif_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    bell_file.touch()
    # Terminal bell for attention
    print("\a", end="", flush=True)


def check_notifications(agent: str) -> list[dict]:
    """Read and acknowledge notifications. Returns list of notification dicts."""
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    if not bell_file.exists():
        return []

    notifications = []
    if notif_file.exists():
        with open(notif_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        notifications.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # Acknowledge
    try:
        bell_file.unlink()
    except Exception:
        pass

    return notifications


def clear_notifications(agent: str):
    """Clear all notifications for an agent."""
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"
    try:
        notif_file.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        bell_file.unlink(missing_ok=True)
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description="agent_sync v6 notifier")
    p.add_argument("agent")
    p.add_argument("--port", type=int, default=9800)
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()

    asyncio.run(run_notifier(args.agent, args.port, args.interval))


if __name__ == "__main__":
    main()
