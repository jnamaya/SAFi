"""Package facade for the external-facing service layer.

I/O and parsing live here so the faculties stay purely logical; import from
this module rather than reaching into the submodules.
"""
from .llm_provider import LLMProvider
from .parsing_utils import (
    robust_json_parse, 
    parse_intellect_response,
    parse_will_response,
    parse_conscience_response
)
from .rag_service import RAGService
from .mcp_manager import MCPManager

__all__ = [
    "LLMProvider",
    "RAGService",
    "MCPManager",
    "robust_json_parse",
    "parse_intellect_response",
    "parse_will_response",
    "parse_conscience_response"
]