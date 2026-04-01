"""agent_sync.server — Lightweight TCP coordination server.

Protocol: newline-delimited JSON messages.
Each message has {"cmd": "...", "agent": "...", ...}
Server replies with {"ok": true/false, "data": ...}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sync-server] %(message)s")
log = logging.getLogger("agent_sync.server")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Server state
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AgentInfo:
    name: str
    status: str = "idle"           # idle | working | waiting | done
    current_task: str = ""
    branch: str = ""               # git branch name
    joined_at: float = 0.0
    last_heartbeat: float = 0.0


@dataclass
class MergeRequest:
    agent: str
    branch: str
    message: str
    timestamp: float = 0.0


@dataclass
class Proposal:
    id: str
    from_agent: str
    text: str
    status: str = "pending"        # pending | approved | rejected
    timestamp: float = 0.0


@dataclass
class ServerState:
    # ── Phase management ──
    # IMPLEMENT → MERGE → TEST → DISCUSS → back to IMPLEMENT or SHUTDOWN
    phase: str = "IMPLEMENT"
    round_number: int = 1

    agents: dict[str, AgentInfo] = field(default_factory=dict)
    # task_id -> assigned agent
    tasks: dict[str, str] = field(default_factory=dict)
    # completed tasks this round: task_id -> agent
    completed_tasks: dict[str, str] = field(default_factory=dict)
    # agent_name -> list of pending messages
    mailboxes: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    # barrier_id -> set of agents that arrived
    barriers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # barrier_id -> expected count
    barrier_counts: dict[str, int] = field(default_factory=dict)
    # barrier_id -> asyncio.Event
    barrier_events: dict[str, asyncio.Event] = field(default_factory=dict)
    # agent_name -> asyncio.Event (for message arrival)
    mail_events: dict[str, asyncio.Event] = field(default_factory=dict)
    # agent_name -> asyncio.Event (for task assignment)
    task_events: dict[str, asyncio.Event] = field(default_factory=dict)
    # pending task queue: list of (task_id, task_description)
    task_queue: list[tuple[str, str]] = field(default_factory=list)
    # merge requests from agents
    merge_requests: list[MergeRequest] = field(default_factory=list)
    # test results
    test_results: list[dict] = field(default_factory=list)
    # proposals
    proposals: list[Proposal] = field(default_factory=list)
    proposal_counter: int = 0
    # phase transition event — agents block on this
    phase_event: asyncio.Event = field(default_factory=asyncio.Event)
    # discussion log
    discussion: list[dict] = field(default_factory=list)


state = ServerState()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Command handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _reply(ok: bool, **kw: Any) -> dict:
    return {"ok": ok, **kw}


async def _handle_join(msg: dict) -> dict:
    name = msg["agent"]
    now = time.time()
    state.agents[name] = AgentInfo(name=name, joined_at=now, last_heartbeat=now)
    state.mail_events[name] = asyncio.Event()
    state.task_events[name] = asyncio.Event()
    log.info("Agent joined: %s (total: %d)", name, len(state.agents))
    return _reply(True, message=f"Joined as {name}")


async def _handle_status(msg: dict) -> dict:
    agents = {
        n: {"status": a.status, "task": a.current_task, "branch": a.branch}
        for n, a in state.agents.items()
    }
    barriers = {k: list(v) for k, v in state.barriers.items()}
    return _reply(True, agents=agents, barriers=barriers,
                  pending_tasks=len(state.task_queue),
                  phase=state.phase, round=state.round_number,
                  merge_requests=len(state.merge_requests),
                  completed_tasks=dict(state.completed_tasks),
                  proposals=[{"id": p.id, "from": p.from_agent,
                              "status": p.status, "text": p.text[:80]}
                             for p in state.proposals])


async def _handle_send(msg: dict) -> dict:
    to = msg["to"]
    payload = {
        "from": msg["agent"],
        "text": msg["text"],
        "ts": time.time(),
    }
    state.mailboxes[to].append(payload)
    evt = state.mail_events.get(to)
    if evt:
        evt.set()
    log.info("Message: %s -> %s (%d chars)", msg["agent"], to, len(msg["text"]))
    return _reply(True)


async def _handle_broadcast(msg: dict) -> dict:
    sender = msg["agent"]
    payload = {"from": sender, "text": msg["text"], "ts": time.time()}
    for name in state.agents:
        if name != sender:
            state.mailboxes[name].append(payload)
            evt = state.mail_events.get(name)
            if evt:
                evt.set()
    log.info("Broadcast from %s to %d agents", sender, len(state.agents) - 1)
    return _reply(True)


async def _handle_listen(msg: dict) -> dict:
    """Block until a message arrives for this agent, or timeout."""
    name = msg["agent"]
    timeout = msg.get("timeout", 300)

    # Already have messages?
    if state.mailboxes[name]:
        msgs = list(state.mailboxes[name])
        state.mailboxes[name].clear()
        return _reply(True, messages=msgs)

    # Wait for mail event
    evt = state.mail_events.get(name)
    if not evt:
        evt = asyncio.Event()
        state.mail_events[name] = evt
    evt.clear()

    try:
        await asyncio.wait_for(evt.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return _reply(True, messages=[], timeout=True)

    msgs = list(state.mailboxes[name])
    state.mailboxes[name].clear()
    return _reply(True, messages=msgs)


async def _handle_barrier(msg: dict) -> dict:
    """Block until all expected agents reach this barrier."""
    bid = msg["barrier_id"]
    name = msg["agent"]
    expected = msg.get("expected", len(state.agents))
    timeout = msg.get("timeout", 600)

    state.barriers[bid].add(name)
    state.barrier_counts[bid] = expected

    if bid not in state.barrier_events:
        state.barrier_events[bid] = asyncio.Event()

    log.info("Barrier %s: %s arrived (%d/%d)",
             bid, name, len(state.barriers[bid]), expected)

    if len(state.barriers[bid]) >= expected:
        state.barrier_events[bid].set()
        return _reply(True, message="barrier released", arrived=list(state.barriers[bid]))

    try:
        await asyncio.wait_for(state.barrier_events[bid].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return _reply(False, message="barrier timeout",
                      arrived=list(state.barriers[bid]))

    return _reply(True, message="barrier released", arrived=list(state.barriers[bid]))


async def _handle_add_task(msg: dict) -> dict:
    """Orchestrator pushes a task to the queue."""
    task_id = msg["task_id"]
    desc = msg.get("description", "")
    state.task_queue.append((task_id, desc))
    # Notify any waiting agents
    for evt in state.task_events.values():
        evt.set()
    log.info("Task added: %s (%d in queue)", task_id, len(state.task_queue))
    return _reply(True, task_id=task_id)


async def _handle_wait_task(msg: dict) -> dict:
    """Agent blocks until a task is available."""
    name = msg["agent"]
    timeout = msg.get("timeout", 600)

    if state.task_queue:
        task_id, desc = state.task_queue.pop(0)
        state.agents[name].status = "working"
        state.agents[name].current_task = task_id
        state.tasks[task_id] = name
        return _reply(True, task_id=task_id, description=desc)

    evt = state.task_events.get(name)
    if not evt:
        evt = asyncio.Event()
        state.task_events[name] = evt
    evt.clear()

    try:
        await asyncio.wait_for(evt.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return _reply(False, message="no tasks available (timeout)")

    if state.task_queue:
        task_id, desc = state.task_queue.pop(0)
        state.agents[name].status = "working"
        state.agents[name].current_task = task_id
        state.tasks[task_id] = name
        return _reply(True, task_id=task_id, description=desc)

    return _reply(False, message="no tasks available")


async def _handle_done_task(msg: dict) -> dict:
    """Agent reports task completion."""
    name = msg["agent"]
    task_id = msg.get("task_id", state.agents.get(name, AgentInfo(name)).current_task)
    result_msg = msg.get("message", "")

    if name in state.agents:
        state.agents[name].status = "idle"
        state.agents[name].current_task = ""

    log.info("Task done: %s by %s — %s", task_id, name, result_msg[:120])
    return _reply(True, task_id=task_id)


async def _handle_heartbeat(msg: dict) -> dict:
    name = msg["agent"]
    if name in state.agents:
        state.agents[name].last_heartbeat = time.time()
    return _reply(True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase & workflow handlers (v2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _handle_set_branch(msg: dict) -> dict:
    """Agent declares its working branch."""
    name = msg["agent"]
    branch = msg["branch"]
    if name in state.agents:
        state.agents[name].branch = branch
    log.info("Branch set: %s -> %s", name, branch)
    return _reply(True, branch=branch)


async def _handle_merge_request(msg: dict) -> dict:
    """Agent signals: my branch is ready to merge into main."""
    name = msg["agent"]
    branch = msg.get("branch", state.agents.get(name, AgentInfo(name)).branch)
    message = msg.get("message", "")

    mr = MergeRequest(agent=name, branch=branch, message=message, timestamp=time.time())
    state.merge_requests.append(mr)

    if name in state.agents:
        state.agents[name].status = "waiting"

    log.info("Merge request: %s (branch: %s) — %s", name, branch, message[:80])

    # Notify orchestrator
    state.mailboxes["__orchestrator__"].append({
        "from": name, "type": "merge_request",
        "text": f"MR from {name}: branch={branch} — {message}",
        "ts": time.time(),
    })
    evt = state.mail_events.get("__orchestrator__")
    if evt:
        evt.set()

    return _reply(True, message=f"Merge request submitted from {name}")


async def _handle_set_phase(msg: dict) -> dict:
    """Orchestrator changes the global phase."""
    new_phase = msg["phase"]
    old_phase = state.phase
    state.phase = new_phase

    if new_phase == "IMPLEMENT":
        state.round_number += 1
        state.merge_requests.clear()
        state.test_results.clear()
        state.completed_tasks.clear()

    log.info("Phase: %s -> %s (round %d)", old_phase, new_phase, state.round_number)

    # Wake all agents waiting on phase change
    state.phase_event.set()
    state.phase_event = asyncio.Event()

    # Broadcast phase change to all agents
    payload = {"from": "__server__", "type": "phase_change",
               "text": f"Phase changed: {old_phase} -> {new_phase} (round {state.round_number})",
               "phase": new_phase, "round": state.round_number, "ts": time.time()}
    for name in state.agents:
        state.mailboxes[name].append(payload)
        evt = state.mail_events.get(name)
        if evt:
            evt.set()

    return _reply(True, phase=new_phase, round=state.round_number)


async def _handle_wait_phase(msg: dict) -> dict:
    """Agent blocks until a specific phase is reached."""
    target = msg["phase"]
    timeout = msg.get("timeout", 600)

    if state.phase == target:
        return _reply(True, phase=state.phase, round=state.round_number)

    try:
        while state.phase != target:
            await asyncio.wait_for(state.phase_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return _reply(False, message=f"timeout waiting for phase {target}",
                      current_phase=state.phase)

    return _reply(True, phase=state.phase, round=state.round_number)


async def _handle_test_result(msg: dict) -> dict:
    """Orchestrator reports test results."""
    passed = msg["passed"]
    output = msg.get("output", "")
    failures = msg.get("failures", [])

    result = {
        "passed": passed, "output": output,
        "failures": failures, "ts": time.time(),
        "round": state.round_number,
    }
    state.test_results.append(result)

    log.info("Test result: %s (round %d, %d failures)",
             "PASS" if passed else "FAIL", state.round_number, len(failures))

    # Broadcast test result to all agents
    payload = {"from": "__orchestrator__", "type": "test_result",
               "text": f"Test {'PASSED' if passed else 'FAILED'}: {output[:200]}",
               "passed": passed, "failures": failures, "ts": time.time()}
    for name in state.agents:
        state.mailboxes[name].append(payload)
        evt = state.mail_events.get(name)
        if evt:
            evt.set()

    return _reply(True, passed=passed)


async def _handle_discuss(msg: dict) -> dict:
    """Agent posts a discussion message visible to all."""
    name = msg["agent"]
    text = msg["text"]

    entry = {"from": name, "text": text, "ts": time.time(),
             "round": state.round_number, "phase": state.phase}
    state.discussion.append(entry)

    # Broadcast to all other agents
    payload = {"from": name, "type": "discussion",
               "text": text, "ts": time.time()}
    for agent_name in state.agents:
        if agent_name != name:
            state.mailboxes[agent_name].append(payload)
            evt = state.mail_events.get(agent_name)
            if evt:
                evt.set()

    log.info("Discussion: %s — %s", name, text[:80])
    return _reply(True)


async def _handle_propose(msg: dict) -> dict:
    """Agent proposes a fix/change to the orchestrator."""
    name = msg["agent"]
    text = msg["text"]

    state.proposal_counter += 1
    pid = f"P{state.proposal_counter}"
    prop = Proposal(id=pid, from_agent=name, text=text,
                    status="pending", timestamp=time.time())
    state.proposals.append(prop)

    # Notify orchestrator
    state.mailboxes["__orchestrator__"].append({
        "from": name, "type": "proposal", "proposal_id": pid,
        "text": f"Proposal {pid} from {name}: {text}",
        "ts": time.time(),
    })
    evt = state.mail_events.get("__orchestrator__")
    if evt:
        evt.set()

    log.info("Proposal %s from %s: %s", pid, name, text[:80])
    return _reply(True, proposal_id=pid)


async def _handle_approve(msg: dict) -> dict:
    """Orchestrator approves a proposal."""
    pid = msg["proposal_id"]
    for p in state.proposals:
        if p.id == pid:
            p.status = "approved"
            # Notify the proposing agent
            payload = {"from": "__orchestrator__", "type": "approval",
                       "text": f"Proposal {pid} APPROVED",
                       "proposal_id": pid, "ts": time.time()}
            state.mailboxes[p.from_agent].append(payload)
            evt = state.mail_events.get(p.from_agent)
            if evt:
                evt.set()
            # Broadcast approval
            for name in state.agents:
                if name != p.from_agent:
                    state.mailboxes[name].append(payload)
                    evt2 = state.mail_events.get(name)
                    if evt2:
                        evt2.set()
            log.info("Proposal %s APPROVED", pid)
            return _reply(True, proposal_id=pid, status="approved")
    return _reply(False, error=f"proposal {pid} not found")


async def _handle_reject(msg: dict) -> dict:
    """Orchestrator rejects a proposal."""
    pid = msg["proposal_id"]
    reason = msg.get("reason", "")
    for p in state.proposals:
        if p.id == pid:
            p.status = "rejected"
            payload = {"from": "__orchestrator__", "type": "rejection",
                       "text": f"Proposal {pid} REJECTED: {reason}",
                       "proposal_id": pid, "ts": time.time()}
            state.mailboxes[p.from_agent].append(payload)
            evt = state.mail_events.get(p.from_agent)
            if evt:
                evt.set()
            log.info("Proposal %s REJECTED: %s", pid, reason[:80])
            return _reply(True, proposal_id=pid, status="rejected")
    return _reply(False, error=f"proposal {pid} not found")


async def _handle_get_discussion(msg: dict) -> dict:
    """Get the full discussion log."""
    round_filter = msg.get("round")
    if round_filter:
        entries = [e for e in state.discussion if e.get("round") == round_filter]
    else:
        entries = list(state.discussion)
    return _reply(True, discussion=entries)


async def _handle_shutdown(msg: dict) -> dict:
    """Orchestrator signals all agents to stop."""
    reason = msg.get("reason", "All tasks completed")
    state.phase = "SHUTDOWN"

    payload = {"from": "__orchestrator__", "type": "shutdown",
               "text": f"SHUTDOWN: {reason}", "ts": time.time()}
    for name in state.agents:
        state.agents[name].status = "done"
        state.mailboxes[name].append(payload)
        evt = state.mail_events.get(name)
        if evt:
            evt.set()

    state.phase_event.set()
    log.info("SHUTDOWN: %s", reason)
    return _reply(True, message="shutdown signal sent")


HANDLERS = {
    "join": _handle_join,
    "status": _handle_status,
    "send": _handle_send,
    "broadcast": _handle_broadcast,
    "listen": _handle_listen,
    "barrier": _handle_barrier,
    "add_task": _handle_add_task,
    "wait_task": _handle_wait_task,
    "done_task": _handle_done_task,
    "heartbeat": _handle_heartbeat,
    # v2: workflow
    "set_branch": _handle_set_branch,
    "merge_request": _handle_merge_request,
    "set_phase": _handle_set_phase,
    "wait_phase": _handle_wait_phase,
    "test_result": _handle_test_result,
    "discuss": _handle_discuss,
    "propose": _handle_propose,
    "approve": _handle_approve,
    "reject": _handle_reject,
    "get_discussion": _handle_get_discussion,
    "shutdown": _handle_shutdown,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TCP server
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    log.info("Connection from %s", addr)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                msg = json.loads(line.decode("utf-8").strip())
            except (json.JSONDecodeError, UnicodeDecodeError):
                resp = _reply(False, error="invalid JSON")
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
                continue

            cmd = msg.get("cmd", "")
            handler = HANDLERS.get(cmd)
            if not handler:
                resp = _reply(False, error=f"unknown command: {cmd}")
            else:
                try:
                    resp = await handler(msg)
                except Exception as e:
                    log.exception("Handler error: %s", cmd)
                    resp = _reply(False, error=str(e))

            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        log.info("Disconnected: %s", addr)


async def run_server(host: str = "127.0.0.1", port: int = 9800):
    server = await asyncio.start_server(_client_handler, host, port)
    log.info("Agent-sync server listening on %s:%d", host, port)
    async with server:
        await server.serve_forever()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="Agent sync server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9800)
    args = parser.parse_args()
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        log.info("Server stopped by user (Ctrl+C)")


if __name__ == "__main__":
    main()
