"""python -m agent_sync <command> [args]"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _add_port(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", type=int, default=9800)


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent_sync",
                                     description="Multi-agent coordination CLI")
    sub = parser.add_subparsers(dest="command")

    # server
    s_server = sub.add_parser("server", help="Start coordination server")
    s_server.add_argument("--host", default="127.0.0.1")
    _add_port(s_server)

    # join
    s_join = sub.add_parser("join", help="Register agent with server")
    s_join.add_argument("agent", help="Agent name")
    _add_port(s_join)

    # status
    s_status = sub.add_parser("status", help="Show all agents and tasks")
    _add_port(s_status)

    # send
    s_send = sub.add_parser("send", help="Send message to another agent")
    s_send.add_argument("from_agent")
    s_send.add_argument("to_agent")
    s_send.add_argument("message")
    _add_port(s_send)

    # broadcast
    s_bc = sub.add_parser("broadcast", help="Send message to all agents")
    s_bc.add_argument("from_agent")
    s_bc.add_argument("message")
    _add_port(s_bc)

    # listen
    s_listen = sub.add_parser("listen", help="Block until message arrives")
    s_listen.add_argument("agent")
    s_listen.add_argument("--timeout", type=int, default=300)
    _add_port(s_listen)

    # barrier
    s_bar = sub.add_parser("barrier", help="Barrier sync — wait for all agents")
    s_bar.add_argument("barrier_id")
    s_bar.add_argument("agent")
    s_bar.add_argument("--expected", type=int, default=5)
    s_bar.add_argument("--timeout", type=int, default=600)
    _add_port(s_bar)

    # add-task
    s_at = sub.add_parser("add-task", help="Push task to queue (orchestrator)")
    s_at.add_argument("task_id")
    s_at.add_argument("--description", default="")
    _add_port(s_at)

    # wait-task
    s_wt = sub.add_parser("wait-task", help="Block until a task is assigned")
    s_wt.add_argument("agent")
    s_wt.add_argument("--timeout", type=int, default=600)
    _add_port(s_wt)

    # done-task
    s_dt = sub.add_parser("done-task", help="Report task completion")
    s_dt.add_argument("agent")
    s_dt.add_argument("--message", default="")
    _add_port(s_dt)

    # heartbeat
    s_hb = sub.add_parser("heartbeat", help="Send heartbeat")
    s_hb.add_argument("agent")
    _add_port(s_hb)

    # ── v2: workflow commands ──

    # set-branch
    s_sb = sub.add_parser("set-branch", help="Declare working branch")
    s_sb.add_argument("agent")
    s_sb.add_argument("branch")
    _add_port(s_sb)

    # merge-request
    s_mr = sub.add_parser("merge-request", help="Request merge into main")
    s_mr.add_argument("agent")
    s_mr.add_argument("--branch", default="")
    s_mr.add_argument("--message", default="")
    _add_port(s_mr)

    # set-phase (orchestrator only)
    s_sp = sub.add_parser("set-phase", help="Set global phase")
    s_sp.add_argument("phase", choices=["IMPLEMENT", "MERGE", "TEST", "DISCUSS", "SHUTDOWN"])
    _add_port(s_sp)

    # wait-phase
    s_wp = sub.add_parser("wait-phase", help="Block until phase is reached")
    s_wp.add_argument("agent")
    s_wp.add_argument("phase")
    s_wp.add_argument("--timeout", type=int, default=600)
    _add_port(s_wp)

    # test-result (orchestrator only)
    s_tr = sub.add_parser("test-result", help="Report test results")
    s_tr.add_argument("--passed", action="store_true")
    s_tr.add_argument("--failed", action="store_true")
    s_tr.add_argument("--output", default="")
    s_tr.add_argument("--failures", nargs="*", default=[])
    _add_port(s_tr)

    # discuss
    s_disc = sub.add_parser("discuss", help="Post discussion message")
    s_disc.add_argument("agent")
    s_disc.add_argument("text")
    _add_port(s_disc)

    # propose
    s_prop = sub.add_parser("propose", help="Propose fix to orchestrator")
    s_prop.add_argument("agent")
    s_prop.add_argument("text")
    _add_port(s_prop)

    # approve (orchestrator only)
    s_appr = sub.add_parser("approve", help="Approve a proposal")
    s_appr.add_argument("proposal_id")
    _add_port(s_appr)

    # reject (orchestrator only)
    s_rej = sub.add_parser("reject", help="Reject a proposal")
    s_rej.add_argument("proposal_id")
    s_rej.add_argument("--reason", default="")
    _add_port(s_rej)

    # get-discussion
    s_gd = sub.add_parser("get-discussion", help="Get discussion log")
    s_gd.add_argument("--round", type=int, default=None, dest="round_num")
    _add_port(s_gd)

    # shutdown (orchestrator only)
    s_sd = sub.add_parser("shutdown", help="Signal all agents to stop")
    s_sd.add_argument("--reason", default="All tasks completed")
    _add_port(s_sd)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    from agent_sync.client import (
        cmd_join, cmd_status, cmd_send, cmd_broadcast,
        cmd_listen, cmd_barrier, cmd_add_task, cmd_wait_task,
        cmd_done_task, cmd_heartbeat,
        cmd_set_branch, cmd_merge_request, cmd_set_phase,
        cmd_wait_phase, cmd_test_result, cmd_discuss,
        cmd_propose, cmd_approve, cmd_reject, cmd_get_discussion,
        cmd_shutdown,
    )

    port = args.port

    if args.command == "server":
        from agent_sync.server import run_server
        try:
            asyncio.run(run_server(args.host, port))
        except KeyboardInterrupt:
            pass
        return 0

    coro = {
        "join": lambda: cmd_join(args.agent, port),
        "status": lambda: cmd_status(port),
        "send": lambda: cmd_send(args.from_agent, args.to_agent, args.message, port),
        "broadcast": lambda: cmd_broadcast(args.from_agent, args.message, port),
        "listen": lambda: cmd_listen(args.agent, args.timeout, port),
        "barrier": lambda: cmd_barrier(args.barrier_id, args.agent, args.expected,
                                        args.timeout, port),
        "add-task": lambda: cmd_add_task(args.task_id, args.description, port),
        "wait-task": lambda: cmd_wait_task(args.agent, args.timeout, port),
        "done-task": lambda: cmd_done_task(args.agent, args.message, port),
        "heartbeat": lambda: cmd_heartbeat(args.agent, port),
        # v2
        "set-branch": lambda: cmd_set_branch(args.agent, args.branch, port),
        "merge-request": lambda: cmd_merge_request(args.agent, args.branch, args.message, port),
        "set-phase": lambda: cmd_set_phase(args.phase, port),
        "wait-phase": lambda: cmd_wait_phase(args.agent, args.phase, args.timeout, port),
        "test-result": lambda: cmd_test_result(
            args.passed and not args.failed, args.output, args.failures, port),
        "discuss": lambda: cmd_discuss(args.agent, args.text, port),
        "propose": lambda: cmd_propose(args.agent, args.text, port),
        "approve": lambda: cmd_approve(args.proposal_id, port),
        "reject": lambda: cmd_reject(args.proposal_id, args.reason, port),
        "get-discussion": lambda: cmd_get_discussion(args.round_num, port),
        "shutdown": lambda: cmd_shutdown(args.reason, port),
    }.get(args.command)

    if coro is None:
        parser.print_help()
        return 1

    return asyncio.run(coro())


if __name__ == "__main__":
    sys.exit(main())
