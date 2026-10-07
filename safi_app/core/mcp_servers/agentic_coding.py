"""Agentic coding MCP server — tool vocabulary for agentic coding clients.

Re-exports the core repository tools and tool declarations from coding_harness
under the modern 'agentic_coding' naming convention.
"""
from .coding_harness import *  # noqa: F401, F403
from .coding_harness import (
    CODING_HARNESS_TOOL_NAMES,
    OPENCODE_TOOL_NAMES,
    SAFI_EXECUTED_TOOLS,
    BUILTIN_TOOL_FUNCTIONS,
    read_file,
    grep,
    glob_files,
    list_directory,
    execute_tool,
)

AGENTIC_TOOL_NAMES = CODING_HARNESS_TOOL_NAMES
