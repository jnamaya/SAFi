"""
This package bundles all external-facing services for the application.

By centralizing I/O-bound and parsing logic here (e.g., LLM calls,
RAG queries, JSON parsing), the core "faculties" can remain
purely logical and testable.

This file makes 'services' a Python package and exports its
primary classes and functions for use by the orchestrator and faculties.
"""
from .llm_provider import LLMProvider
from .parsing_utils import (
    robust_json_parse, 
    parse_intellect_response,
    parse_will_response,
    parse_conscience_response
)
from .rag_service import RAGService

__all__ = [
    "LLMProvider",
    "RAGService",
    "robust_json_parse",
    "parse_intellect_response",
    "parse_will_response",
    "parse_conscience_response"
]