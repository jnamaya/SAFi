import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from safi_app.core.orchestrator import SAFi
import numpy as np

@pytest.mark.asyncio
class TestOrchestrator:

    @pytest.fixture
    def mock_db(self):
        """Mock the database calls used in process_prompt."""
        with patch('safi_app.core.orchestrator.db') as mock_db:
            # Memory Summary
            mock_db.fetch_conversation_summary.return_value = "Summary"
            mock_db.fetch_user_profile_memory.return_value = {}
            mock_db.get_latest_spirit_memory.return_value = {"mu": [0.5, 0.5]}
            mock_db.load_spirit_memory.return_value = {"mu": [0.5, 0.5], "turn": 1}
            mock_db.fetch_chat_history_for_conversation.return_value = [] # New convo
            yield mock_db

    async def test_process_prompt_happy_path(self, mock_config, mock_llm_provider, basic_values, mock_db):
        """
        User Prompt -> Intellect (OK) -> Will (Approve) -> Output
        """
        # Setup Orchestrator
        # Mocking LLMProvider returning distinct values for Intellect vs Will
        # mock_llm_provider.generate_text.return_value = ("Draft Answer", "Reflection", {}) # OLD
        mock_llm_provider.run_intellect.return_value = ("Draft Answer", "Reflection", "Context")
        mock_llm_provider.run_will.return_value = ("approve", "Looks good")

        safi = SAFi(
            config=mock_config(), 
            value_set=basic_values,
            intellect_model="gpt-4o",
            will_model="gpt-4o",
            conscience_model="gpt-4o"
        )
        safi.llm_provider = mock_llm_provider # Force inject mock
        safi.intellect_engine.llm_provider = mock_llm_provider
        safi.will_gate.llm_provider = mock_llm_provider

        # Run
        result = await safi.process_prompt("Hello", "user1", "chat1")

        # Verify
        assert result["finalOutput"] == "Draft Answer"
        assert result["willDecision"] == "approve"
        
        # Verify Audit thread was spawned
        # We can't easily check threads in unit tests without complex waiting, 
        # but we can check the Orchestrator called submit on the executor?
        # Ideally, we mock the executor too, but SAFi inits it internally.
        # Let's trust the return value for now.

    async def test_process_prompt_reflexion(self, mock_config, mock_llm_provider, basic_values, mock_db):
        """
        User Prompt -> Intellect (Bad) -> Will (Block) -> 
        Reflexion -> Intellect (Good) -> Will (Approve) -> Output
        """
        safi = SAFi(config=mock_config(), value_set=basic_values)
        safi.llm_provider = mock_llm_provider
        safi.intellect_engine.llm_provider = mock_llm_provider
        safi.will_gate.llm_provider = mock_llm_provider

        # Scenario:
        # 1. Intellect generates "Bad Answer"
        # 2. Will rejects "Bad Answer"
        # 3. Intellect retry generates "Good Answer"
        # 4. Will approves "Good Answer"
        
        # mock_llm_provider.generate_text.side_effect = ... # OLD
        mock_llm_provider.run_intellect.side_effect = [
            ("Bad Answer", "R1", "C1"),  # 1st attempt
            ("Good Answer", "R2", "C2")  # 2nd attempt (Reflexion)
        ]
        
        mock_llm_provider.run_will.side_effect = [
            ("violation", "Bad"),      # 1st evaluation
            ("approve", "Good")        # 2nd evaluation
        ]

        result = await safi.process_prompt("Test", "user1", "chat1")

        assert result["finalOutput"] == "Good Answer"
        assert result["willDecision"] == "approve"
        # Check that we actually called generate twice
        assert mock_llm_provider.run_intellect.call_count == 2
        # Check that we called will twice
        assert mock_llm_provider.run_will.call_count == 2

    async def test_process_prompt_block(self, mock_config, mock_llm_provider, basic_values, mock_db):
        """
        Reflexion Fails: Both drafts are blocked.
        """
        safi = SAFi(config=mock_config(), value_set=basic_values)
        safi.llm_provider = mock_llm_provider
        safi.intellect_engine.llm_provider = mock_llm_provider
        safi.will_gate.llm_provider = mock_llm_provider

        # Both attempts generate junk
        # mock_llm_provider.generate_text.return_value = ... # OLD
        mock_llm_provider.run_intellect.return_value = ("Bad Answer", "R", "C")
        
        # Both attempts are violated
        mock_llm_provider.run_will.return_value = ("violation", "Still bad")

        result = await safi.process_prompt("Test", "user1", "chat1")

        assert "Blocked" in result["finalOutput"]
        assert result["willDecision"] == "violation"
