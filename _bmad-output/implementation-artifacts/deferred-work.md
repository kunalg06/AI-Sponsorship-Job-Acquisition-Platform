# Deferred Work Ledger

- source_spec: `_bmad-output/implementation-artifacts/spec-mcp-tool-wrappers.md`
  summary: `mcp_server.tools.track_application` has no audit trail (who/when/what) for its mutating calls (mark applied/discarded).
  evidence: An MCP client can trigger a permanent tracker-state mutation with no logging anywhere of the invocation, making it impossible to reconstruct after the fact what an autonomous agent changed and when — flagged in the 2026-07-11 adversarial review of `spec-mcp-tool-wrappers.md`.
