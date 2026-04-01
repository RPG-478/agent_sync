"""agent_sync — Multi-agent coordination over TCP sockets.

Usage:
    python -m agent_sync server   [--port 9800]
    python -m agent_sync join     <agent_name> [--port 9800]
    python -m agent_sync wait     <agent_name> [--timeout 600]
    python -m agent_sync done     <agent_name> [--message "..."]
    python -m agent_sync barrier  <barrier_id> <agent_name> [--timeout 600]
    python -m agent_sync send     <from_agent> <to_agent> <message>
    python -m agent_sync listen   <agent_name> [--timeout 300]
    python -m agent_sync status
    python -m agent_sync broadcast <from_agent> <message>
"""
