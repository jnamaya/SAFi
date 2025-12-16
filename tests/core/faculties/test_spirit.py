import pytest
import numpy as np
from safi_app.core.faculties.spirit import SpiritIntegrator

class TestSpiritIntegrator:
    
    def test_spirit_init(self, basic_values):
        spirit = SpiritIntegrator(values=basic_values, beta=0.9)
        
        # Check weights are extracted correctly (ordered)
        assert len(spirit.value_weights) == 2
        assert spirit.value_weights[0] == 1.0
        assert spirit.value_weights[1] == 0.5
        
        # Check normalization
        assert "honesty" in spirit._norm_values
        assert "harm reduction" in spirit._norm_values

    def test_compute_perfect_match(self, basic_values):
        """
        If current action perfectly matches values (score=1.0), 
        memory should move towards positive.
        """
        spirit = SpiritIntegrator(values=basic_values, beta=0.5) # Low beta for fast testing
        
        mu_tm1 = {} # Neutral start (New Dict format)
        
        # Ledger says we did great
        ledger = [
            {"value": "Honesty", "score": 1, "confidence": 1.0},
            {"value": "Harm Reduction", "score": 1, "confidence": 1.0}
        ]
        
        score, note, mu_new, p_t, drift, _ = spirit.compute(ledger, mu_tm1)
        
        # p_t calculation: weight * score
        assert p_t[0] == 1.0
        assert p_t[1] == 0.5
        
        # Update: 0.5*0 + 0.5*p_t = 0.5 * p_t
        # Access via KEYS now
        assert mu_new["honesty"] == 0.5
        assert mu_new["harm reduction"] == 0.25
        
        assert score > 5 # Should be positive spirit score

    def test_compute_drift(self, basic_values):
        """
        If memory is fully POSITIVE but action is NEGATIVE, drift should be high.
        """
        spirit = SpiritIntegrator(values=basic_values, beta=0.9)
        
        # Established memory: Fully committed to Honesty
        mu_tm1 = {"honesty": 1.0, "harm reduction": 0.0}
        
        # Action: Totally dishonest
        ledger = [
            {"value": "Honesty", "score": -1, "confidence": 1.0},
            {"value": "Harm Reduction", "score": 0, "confidence": 1.0} # Irrelevant here
        ]
        
        _, _, _, p_t, drift, _ = spirit.compute(ledger, mu_tm1)
        
        # p_t = [-1.0, 0.0]
        # mu_tm1(vec) = [1.0, 0.0]
        # These are opposite vectors. Cosine sim = -1. Drift = 1 - (-1) = 2.
        
        assert drift is not None
        assert drift > 1.0 # Significant drift

    def test_compute_missing_keys(self, basic_values):
        """
        If ledger is missing a value, it shouldn't crash.
        """
        spirit = SpiritIntegrator(values=basic_values)
        mu_tm1 = np.zeros(2) # Legacy Array input
        
        # Only Honest, missing Harm Reduction
        ledger = [
            {"value": "Honesty", "score": 1, "confidence": 1.0}
        ]
        
        score, note, mu_new, _, _, _ = spirit.compute(ledger, mu_tm1)
        
        # Should detect the missing value
        assert "Ledger missing" in note
        # Should not update memory (safe fallback)
        assert np.array_equal(mu_new, mu_tm1)
