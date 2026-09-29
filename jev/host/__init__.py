"""Code that runs inside the DT application process.

Nothing in this package may be imported by the controller side (CLI, MCP server,
agent runner): it needs PySide6 and DT, which only the host interpreter has.
"""
