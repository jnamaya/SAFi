"""
Registrations for the plugins that ship with SAFi. Imported once by the
orchestrator; importing this module IS the registration.
"""
from .bible_scholar_readings import handle_bible_scholar_commands

PLUGIN_REGISTRATIONS = [
    ({"the bible scholar", "the_bible_scholar"}, handle_bible_scholar_commands),
]
