"""
Registrations for the plugins that ship with SAFi. Imported once by the
orchestrator; importing this module IS the registration.

The Bible Scholar's readings plugin serves both name forms the orchestrator
can carry (display-derived and sanitized) — the same two strings the handler
itself checks internally, kept as belt-and-braces since the handler predates
the registry.

The fiduciary_data plugin is deliberately NOT registered. Its dispatch was
removed in v1.3 (81e27b0) when the fiduciary moved to governed MCP tools for
market data, and only its import lingered in the orchestrator until 2026-08-13.
Registering it here would resurrect retired behavior — two data paths for one
agent. The module stays in plugins/ for reference; register it consciously or
delete it, but do not let it drift back in.
"""
from .registry import register_plugin
from .bible_scholar_readings import handle_bible_scholar_commands

register_plugin(
    {"the bible scholar", "the_bible_scholar"},
    handle_bible_scholar_commands,
)
