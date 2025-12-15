import pytest
from unittest.mock import AsyncMock
from safi_app.core.faculties.will import WillGate

@pytest.mark.asyncio
class TestWillGate:

    async def test_evaluate_approve(self, mock_llm_provider, basic_values):
        # Setup
        gate = WillGate(llm_provider=mock_llm_provider, values=basic_values)
        
        # Configure Mock to approve
        mock_llm_provider.run_will.return_value = ("approve", "All good")
        
        # Action
        decision, reason = await gate.evaluate(user_prompt="Hi", draft_answer="Hello")
        
        # Assert
        assert decision == "approve"
        assert reason == "All good"
        
        # verify provider was called
        mock_llm_provider.run_will.assert_called_once()

    async def test_evaluate_violation(self, mock_llm_provider, basic_values):
        gate = WillGate(llm_provider=mock_llm_provider, values=basic_values)
        
        mock_llm_provider.run_will.return_value = ("violation", "Too harmful")
        
        decision, reason = await gate.evaluate(user_prompt="Kill him", draft_answer="Okay I will")
        
        assert decision == "violation"
        assert reason == "Too harmful"

    async def test_caching(self, mock_llm_provider, basic_values):
        gate = WillGate(llm_provider=mock_llm_provider, values=basic_values)
        mock_llm_provider.run_will.return_value = ("approve", "Cached")
        
        # First Call
        await gate.evaluate(user_prompt="A", draft_answer="B")
        
        # Second Call (Same inputs)
        await gate.evaluate(user_prompt="A", draft_answer="B")
        
        # Expect only ONE call to LLM
        assert mock_llm_provider.run_will.call_count == 1

    async def test_system_prompt_construction(self, mock_llm_provider, basic_values):
        """
        Verify that the prompt sent to the LLM actually contains our values.
        """
        gate = WillGate(llm_provider=mock_llm_provider, values=basic_values)
        
        await gate.evaluate(user_prompt="X", draft_answer="Y")
        
        # Inspect arguments called on the mock
        call_args = mock_llm_provider.run_will.call_args
        kwargs = call_args.kwargs
        system_prompt = kwargs["system_prompt"]
        
        # Check that value names appear in the prompt
        assert "Honesty" in system_prompt
        assert "Harm Reduction" in system_prompt
        assert "Do not approve drafts that reduce alignment" in system_prompt
