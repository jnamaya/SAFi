import pytest
from unittest.mock import AsyncMock
from safi_app.core.faculties.conscience import ConscienceAuditor

@pytest.mark.asyncio
class TestConscienceAuditor:

    async def test_evaluate_ledger_formation(self, mock_llm_provider, basic_values):
        """Verify standard audit flow returns a ledger."""
        auditor = ConscienceAuditor(
            llm_provider=mock_llm_provider,
            values=basic_values,
            profile={},
            prompt_config={"prompt_template": "Reflect on {rubrics_str}..."}
        )
        
        # Mock expected ledger response
        mock_ledger = [
            {"value": "Honesty", "score": 1, "confidence": 0.9},
            {"value": "Harm Reduction", "score": 0, "confidence": 0.5}
        ]
        mock_llm_provider.run_conscience.return_value = mock_ledger
        
        ledger = await auditor.evaluate(
            final_output="Output " * 20, # > 100 chars
            user_prompt="Input " * 20,   # > 100 chars
            reflection="Reflection",
            retrieved_context="Context"
        )
        
        assert len(ledger) == 2
        assert ledger[0]["value"] == "Honesty"
        assert ledger[1]["score"] == 0
        
        mock_llm_provider.run_conscience.assert_called_once()
        
    async def test_evaluate_empty_response(self, mock_llm_provider, basic_values):
        """Verify empty response handling."""
        auditor = ConscienceAuditor(llm_provider=mock_llm_provider, values=basic_values)
        
        # Mock failure/empty return
        mock_llm_provider.run_conscience.return_value = []
        
        ledger = await auditor.evaluate(
            final_output="Out", 
            user_prompt="In", 
            reflection="Ref", 
            retrieved_context="Ctx"
        )
        
        assert ledger == []
        # Should not crash
