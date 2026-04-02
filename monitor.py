#!/usr/bin/env python3
"""agent_sync v6 Monitor — Live dashboard for 2-agent coordination.

Usage: python agent_sync/monitor.py [--port 9800] [--interval 2]

Shows:
  ┌─ Phase / Round / Implementer
  ├─ Agent status + pending messages
  ├─ Recent discussion (last 10)
  └─ Live event log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime


async def tcp_cmd(cmd: dict, port: int, timeout: float = 3) -> dict | None:
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


def clear():
    os.system("cls" if os.name == "nt" else "clear")


PHASE_EMOJI = {
    "IMPLEMENT": "🔨",
    "TEST": "🧪",
    "DISCUSS": "💬",
    "SHUTDOWN": "🛑",
}

AGENT_COLORS = {
    "agent-a": "\033[96m",  # cyan
    "agent-b": "\033[93m",  # yellow
    "user": "\033[92m",     # green
    "__server__": "\033[90m",  # gray
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def colorize(agent: str, text: str) -> str:
    c = AGENT_COLORS.get(agent, "")
    return f"{c}{text}{RESET}"


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def render_dashboard(status: dict, discussion: list[dict],
                     peeks: dict[str, dict | None],
                     events: list[str]) -> str:
    d = status.get("data", {})
    phase = d.get("phase", "?")
    rnd = d.get("round", 0)
    impl = d.get("implementer", "?")
    agents = d.get("agents", {})
    emoji = PHASE_EMOJI.get(phase, "❓")

    lines = []
    w = 64

    # Header
    lines.append(f"{BOLD}{'═' * w}{RESET}")
    lines.append(f"{BOLD}  agent_sync v6 — Live Monitor{RESET}")
    lines.append(f"{'═' * w}")

    # Phase bar
    lines.append(f"  {emoji} Phase: {BOLD}{phase}{RESET}   Round: {BOLD}{rnd}{RESET}   Implementer: {BOLD}{colorize(impl, impl)}{RESET}")
    lines.append(f"{'─' * w}")

    # Agents
    lines.append(f"  {BOLD}Agents:{RESET}")
    all_peeks = peeks or {}
    for name in sorted(agents.keys()):
        info = agents.get(name)
        if info:
            peek = all_peeks.get(name)
            pending = peek.get("pending", 0) if peek else "?"
            mail_icon = f"📬 {pending}" if pending and pending != "?" and pending > 0 else "📭 0"
            lines.append(f"    {colorize(name, name)}  {mail_icon} pending")
        else:
            lines.append(f"    {DIM}{name}  (not joined){RESET}")
    lines.append(f"{'─' * w}")

    # Discussion (last 10)
    lines.append(f"  {BOLD}💬 Discussion (last 10):{RESET}")
    if discussion:
        recent = discussion[-10:]
        for entry in recent:
            agent = entry.get("agent", "?")
            text = entry.get("text", "")
            ts = fmt_ts(entry.get("ts", 0))
            r = entry.get("round", "?")
            # Truncate long texts
            if len(text) > 80:
                text = text[:77] + "..."
            lines.append(f"    {DIM}[R{r} {ts}]{RESET} {colorize(agent, agent)}: {text}")
    else:
        lines.append(f"    {DIM}(no discussion yet){RESET}")
    lines.append(f"{'─' * w}")

    # Event log (last 8)
    lines.append(f"  {BOLD}📋 Events:{RESET}")
    for evt in events[-8:]:
        lines.append(f"    {DIM}{evt}{RESET}")
    if not events:
        lines.append(f"    {DIM}(waiting...){RESET}")
    lines.append(f"{'═' * w}")
    lines.append(f"  {DIM}Ctrl+C to exit monitor{RESET}")

    return "\n".join(lines)


async def monitor(port: int, interval: float):
    events: list[str] = []
    prev_phase = ""
    prev_round = 0
    prev_disc_len = 0

    print(f"Connecting to agent_sync server on port {port}...")

    while True:
        status = await tcp_cmd({"cmd": "status"}, port)
        if not status or not status.get("ok"):
            clear()
            print(f"⏳ Waiting for server on port {port}...")
            await asyncio.sleep(interval)
            continue

        discussion = []
        disc_resp = await tcp_cmd({"cmd": "get-discussion"}, port)
        if disc_resp and disc_resp.get("ok"):
            discussion = disc_resp.get("discussion", [])

        peek_a = await tcp_cmd({"cmd": "peek", "agent": "agent-a"}, port)
        peek_b = await tcp_cmd({"cmd": "peek", "agent": "agent-b"}, port)

        # Peek all agents
        d = status.get("data", {})
        peeks: dict[str, dict | None] = {}
        for agent_name in d.get("agents", {}).keys():
            peeks[agent_name] = await tcp_cmd({"cmd": "peek", "agent": agent_name}, port)
        phase = d.get("phase", "?")
        rnd = d.get("round", 0)

        if phase != prev_phase and prev_phase:
            events.append(f"{datetime.now().strftime('%H:%M:%S')} Phase: {prev_phase} → {phase}")
        if rnd != prev_round and prev_round:
            events.append(f"{datetime.now().strftime('%H:%M:%S')} Round {prev_round} → {rnd}")
        if len(discussion) > prev_disc_len:
            new_msgs = discussion[prev_disc_len:]
            for m in new_msgs:
                events.append(
                    f"{fmt_ts(m.get('ts', 0))} {m.get('agent', '?')}: {m.get('text', '')[:50]}")

        prev_phase = phase
        prev_round = rnd
        prev_disc_len = len(discussion)

        clear()
        print(render_dashboard(status, discussion, peeks, events))

        if phase == "SHUTDOWN":
            print("\n🛑 Server in SHUTDOWN. Monitor exiting.")
            break

        await asyncio.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="agent_sync v6 live monitor")
    p.add_argument("--port", type=int, default=9800)
    p.add_argument("--interval", type=float, default=2.0,
                   help="Refresh interval in seconds")
    args = p.parse_args()
    try:
        asyncio.run(monitor(args.port, args.interval))
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


if __name__ == "__main__":
    main()
