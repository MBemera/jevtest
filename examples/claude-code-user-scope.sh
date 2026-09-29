#!/usr/bin/env sh
# Register Jev for Claude Code in every project (user scope) instead of via this repo's .mcp.json.
# Run from the jevtest checkout after `pip install -e .` in the venv that also has DT installed.
claude mcp add --scope user jev -e JEV_DT_PATH="$(cd ../DT && pwd)" -- "$(command -v python)" -m jev mcp
