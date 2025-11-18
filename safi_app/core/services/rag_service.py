"""
Defines the RAGService.

This class is the ONLY part of the application that knows how to:
1.  Import and instantiate the Retriever.
2.  Perform a search using the Retriever.
3.  Format the raw search results (metadata dicts) into a 
    single context string for the Intellect to use.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any

# Import the Retriever from its sibling directory
try:
    from ..retriever import Retriever
except (ImportError, ValueError) as e:
    logging.critical(f"Failed to import Retriever: {e}. Ensure safi_app/core/retriever.py exists.")
    # Define a mock class if import fails so the app can load but RAG is disabled
    class Retriever:
        def __init__(self, *args, **kwargs):
            logging.error("Using Mock Retriever class. Import failed.")
        def search(self, *args, **kwargs) -> List[Dict[str, Any]]:
            return []


class RAGService:
    """
    A service layer that abstracts the Retriever.
    
    It handles the initialization of the Retriever and formats its
    output into a clean string.
    """
    def __init__(self, knowledge_base_name: str | None):
        """
        Initializes the RAGService and the underlying Retriever.

        Args:
            knowledge_base_name: The name of the knowledge base to load.
                                 If None, RAG will be disabled.
        """
        self.log = logging.getLogger(self.__class__.__name__)
        if knowledge_base_name:
            try:
                # Initialize the actual retriever class
                self.retriever = Retriever(knowledge_base_name=knowledge_base_name)
                self.enabled = True if self.retriever.index else False
                if not self.enabled:
                    self.log.warning(f"RAGService enabled, but Retriever failed to load index for {knowledge_base_name}.")
            except Exception as e:
                self.log.error(f"Failed to initialize Retriever for {knowledge_base_name}: {e}")
                self.retriever = None
                self.enabled = False
        else:
            # RAG is explicitly disabled
            self.retriever = None
            self.enabled = False
            self.log.info("RAGService disabled (no knowledge_base_name provided).")

    async def get_context(self, query: str, format_string: str) -> str:
        """
        Searches for context and returns a formatted string.

        Args:
            query: The user's search query.
            format_string: A Python format-string to apply to each
                           metadata dictionary (e.g., "{source}: {text_chunk}").

        Returns:
            A single string containing all formatted context, or
            "[NO DOCUMENTS FOUND]" if no results.
        """
        if not self.enabled or not self.retriever:
            return "" # Return empty string if RAG is disabled

        try:
            # --- 1. Perform the search ---
            # Note: The retriever's search method is synchronous.
            # If this becomes a bottleneck, it should be run in a thread.
            retrieved_docs = self.retriever.search(query)
            
            if not retrieved_docs:
                return "[NO DOCUMENTS FOUND]"

            # --- 2. Format the results ---
            formatted_chunks = []
            for doc in retrieved_docs:
                try:
                    # Use **doc to unpack the metadata dictionary into the format string
                    formatted_chunks.append(format_string.format(**doc))
                except KeyError as e:
                    # Fallback: if format fails (e.g., missing key), just use the text_chunk
                    self.log.warning(f"RAG format string failed for key {e}. Falling back to 'text_chunk'.")
                    if "text_chunk" in doc:
                        formatted_chunks.append(doc["text_chunk"])

            return "\n\n".join(formatted_chunks)

        except Exception as e:
            self.log.exception(f"Error during RAG search for query: {query}")
            return f"[RAG ERROR: {e}]"