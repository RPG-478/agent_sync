"""agent_sync.client — CLI client for agent coordination.

Each command connects, sends one request, prints the result, and exits.
Blocking commands (listen, barrier, wait_task) keep the connection open.
"""
from __future__ import annotations

import asyncio
import json
import sys


async def _request(msg: dict, host: str = "127.0.0.1", port: int = 9800,
                   timeout: float | None = None,
                   retry: bool = True, retry_interval: float = 3.0,
                   max_retries: int = 60) -> dict:
    """Send a single JSON message and return the response.
    
    If retry=True, keeps trying to connect until the server is available.
    """
    attempts = 0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            break
        except (ConnectionRefusedError, OSError) as e:
            attempts += 1
            if not retry or attempts >= max_retries:
                return {"ok": False, "error": f"cannot connect to server ({e})"}
            print(f"[agent_sync] Waiting for server on port {port}... (attempt {attempts})",
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


def _print_result(resp: dict) -> int:
    """Pretty-print response and return exit code."""
    if resp.get("ok"):
        # Remove 'ok' key for cleaner output
        data = {k: v for k, v in resp.items() if k != "ok"}
        if data:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("OK")
        return 0
    else:
        print(f"ERROR: {resp.get('error', resp.get('message', 'unknown'))}", file=sys.stderr)
        return 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Individual commands
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_join(agent: str, port: int) -> int:
    return _print_result(await _request({"cmd": "join", "agent": agent}, port=port))


async def cmd_status(port: int) -> int:
    return _print_result(await _request({"cmd": "status"}, port=port))


async def cmd_send(from_: str, to: str, text: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "send", "agent": from_, "to": to, "text": text}, port=port))


async def cmd_broadcast(from_: str, text: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "broadcast", "agent": from_, "text": text}, port=port))


async def cmd_listen(agent: str, timeout: int, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "listen", "agent": agent, "timeout": timeout},
        port=port, timeout=timeout))


async def cmd_barrier(barrier_id: str, agent: str, expected: int,
                      timeout: int, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "barrier", "agent": agent, "barrier_id": barrier_id,
         "expected": expected, "timeout": timeout},
        port=port, timeout=timeout))


async def cmd_add_task(task_id: str, description: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "add_task", "task_id": task_id, "description": description},
        port=port))


async def cmd_wait_task(agent: str, timeout: int, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "wait_task", "agent": agent, "timeout": timeout},
        port=port, timeout=timeout))


async def cmd_done_task(agent: str, message: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "done_task", "agent": agent, "message": message},
        port=port))


async def cmd_heartbeat(agent: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "heartbeat", "agent": agent}, port=port))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v2: Workflow commands
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_set_branch(agent: str, branch: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "set_branch", "agent": agent, "branch": branch}, port=port))


async def cmd_merge_request(agent: str, branch: str, message: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "merge_request", "agent": agent, "branch": branch,
         "message": message}, port=port))


async def cmd_set_phase(phase: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "set_phase", "phase": phase}, port=port))


async def cmd_wait_phase(agent: str, phase: str, timeout: int, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "wait_phase", "agent": agent, "phase": phase, "timeout": timeout},
        port=port, timeout=timeout))


async def cmd_test_result(passed: bool, output: str, failures: list, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "test_result", "passed": passed, "output": output,
         "failures": failures}, port=port))


async def cmd_discuss(agent: str, text: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "discuss", "agent": agent, "text": text}, port=port))


async def cmd_propose(agent: str, text: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "propose", "agent": agent, "text": text}, port=port))


async def cmd_approve(proposal_id: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "approve", "proposal_id": proposal_id}, port=port))


async def cmd_reject(proposal_id: str, reason: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "reject", "proposal_id": proposal_id, "reason": reason}, port=port))


async def cmd_get_discussion(round_num: int | None, port: int) -> int:
    msg: dict = {"cmd": "get_discussion"}
    if round_num is not None:
        msg["round"] = round_num
    return _print_result(await _request(msg, port=port))


async def cmd_shutdown(reason: str, port: int) -> int:
    return _print_result(await _request(
        {"cmd": "shutdown", "reason": reason}, port=port))
