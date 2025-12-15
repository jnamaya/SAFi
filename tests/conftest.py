import pytest
from unittest.mock import AsyncMock, MagicMock
from safi_app.core.services import LLMProvider
from safi_app.config import Config

@pytest.fixture
def mock_llm_provider():
    """
    Creates a mock LLMProvider that simulates AI responses
    without making real network calls.
    """
    provider = MagicMock(spec=LLMProvider)
    
    # Configure provider's internal clients dict to be empty or mocked as needed
    provider.clients = {}
    
    # Mock the text generation method
    # Since it's often awaited, we make it an AsyncMock
    provider.generate_text = AsyncMock()
    provider.generate_text.return_value = "Mocked AI Response"

    # Mock the Will Gate evaluation
    provider.run_will = AsyncMock()
    # Default to "approve"
    provider.run_will.return_value = ("approve", "Looks good to me.")
    
    return provider

@pytest.fixture
def mock_config():
    """
    Provides a safe test configuration.
    """
    class TestConfig(Config):
        # Override critical settings
        LOG_DIR = "tests/logs"
        SPIRIT_BETA = 0.9
        OPENAI_API_KEY = "sk-test-key"
        GROQ_API_KEY = "gsk-test-key"
    return TestConfig

@pytest.fixture
def basic_values():
    return [
        {"value": "Honesty", "weight": 1.0},
        {"value": "Harm Reduction", "weight": 0.5}
    ]
