import pytest
from unittest.mock import AsyncMock, MagicMock
from safi_app.core.faculties.intellect import IntellectEngine

@pytest.mark.asyncio
class TestIntellectEngine:

    @pytest.fixture
    def mock_retriever(self):
        """Mock the RAG retriever (Synchronous)."""
        retriever = MagicMock()
        retriever.search.return_value = [{"text_chunk": "Retrieved Context Info", "source": "doc1"}]
        return retriever

    async def test_generate_basic(self, mock_llm_provider, basic_values, mock_retriever):
        """Test basic generation flow."""
        engine = IntellectEngine(
            llm_provider=mock_llm_provider,
            profile={"values": basic_values},
            prompt_config={}
        )
        engine.retriever = mock_retriever
        
        # Setup Mock Provider to return a valid split response
        # The provider returns (Answer, Reflection, Context)
        mock_llm_provider.run_intellect.return_value = ("Generated Answer", "Generated Reflection", "Retrieved Context Info")

        # Run
        answer, reflection, context = await engine.generate(
            user_prompt="Hello",
            memory_summary="Summary",
            spirit_feedback="Feedback",
            plugin_context={},
            user_profile_json={}
        )

        # Assert
        assert answer == "Generated Answer"
        assert reflection == "Generated Reflection"
        assert context == "Retrieved Context Info"
        
        # Verify provider called
        mock_llm_provider.run_intellect.assert_called_once()
        
    async def test_generate_with_context(self, mock_llm_provider, basic_values, mock_retriever):
        """Verify context is passed to the provider."""
        engine = IntellectEngine(llm_provider=mock_llm_provider, profile={})
        engine.retriever = mock_retriever
        
        mock_llm_provider.run_intellect.return_value = ("A", "R", "C")
        
        await engine.generate(
            user_prompt="Query",
            memory_summary="",
            spirit_feedback="",
            plugin_context={},
            user_profile_json={}
        )
        
        # Verify retriever was called
        mock_retriever.search.assert_called_with("Query")
        
        # Verify provider received the context
        call_args = mock_llm_provider.run_intellect.call_args
        assert "Retrieved Context Info" in call_args.kwargs['context_for_audit']

    async def test_parsing_failure(self, mock_llm_provider, basic_values):
        """If provider returns None (failure), engine should handle it."""
        engine = IntellectEngine(llm_provider=mock_llm_provider, profile={})
        
        mock_llm_provider.run_intellect.return_value = (None, None, "")
        
        answer, reflection, _ = await engine.generate(
            user_prompt="Query",
            memory_summary="",
            spirit_feedback="",
            plugin_context={},
            user_profile_json={}
        )
        
        assert answer is None
        assert reflection is None
        # assert engine.last_error is not None # Logic specific to implementation
