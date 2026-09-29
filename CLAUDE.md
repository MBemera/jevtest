@AGENTS.md

## Claude Code specifics

- `.mcp.json` registers the `jev` MCP server (tools such as `snapshot`, `click`, `type_text`,
  `report_issue`, `run_qa_agents`). Approve it when Claude Code asks. It uses `$JEV_PYTHON` if set,
  otherwise `python`; that interpreter must be able to `import jev` (run `pip install -e .` here).
- The `/qa` command (`.claude/commands/qa.md`) runs a QA session on a mission; the `dt-qa` skill
  (`.claude/skills/dt-qa/`) describes the full workflow and is loaded automatically for QA requests.
- Screenshots from the `screenshot` tool come back as images you can inspect directly.
