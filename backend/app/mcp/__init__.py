"""OpsReader MCP interface for OpsRadar.

Exposes both process-intelligence tools and request-coordination tools
to MCP-aware clients. Stdio mode supports trusted local clients, while
remote HTTP mode supports per-request bearer auth for multi-user access.

Available tool families:
- event-log and mining analysis
- request and approval coordination
- audit and friction summaries
- safe lifecycle write-back actions
"""
