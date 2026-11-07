"""Streamable-HTTP MCP server for an OpenProject task queue.

The task-queue logic is ported from homelab-mcp's openproject tools (MIT, same
author; LICENSE.homelab-mcp); identity comes from each request's own
OpenProject API token instead of a server-side token map.
"""

__version__ = "0.1.0"
