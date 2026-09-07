"""
Unit tests for adaptive preprocessing engine (Phase 5).
"""
import pytest
import numpy as np
from app.ocr.adaptive_preprocessing import ImageQualityAnalyzer, AdaptivePreprocessor


def test_clean_digital_image_passthrough():
    # Synthetic clean high-contrast sharp image
    img = np.full((500, 500, 3), 255, dtype=np.uint8)
    # Add sharp black text-like blocks
    img[100:150, 100:400] = 0
    img[200:250, 100:400] = 0

    processed, decision = AdaptivePreprocessor.process(img)
    assert decision.metrics.is_clean_digital or decision.strategy_name in ("PASS_THROUGH_CLEAN_DIGITAL", "STANDARD_PASSTHROUGH")
    assert processed.shape == img.shape


def test_low_contrast_triggers_clahe():
    # Low contrast faded image (gray levels 120-130)
    img = np.random.randint(120, 130, (300, 300, 3), dtype=np.uint8)

    processed, decision = AdaptivePreprocessor.process(img)
    assert decision.metrics.is_low_contrast
    assert "CLAHE_CONTRAST_ENHANCEMENT" in decision.operations_applied
