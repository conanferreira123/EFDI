"""
Classification engine factory.

Mirrors app/ocr/factory.py's pattern. "rule_based" is the default,
always-available engine. "ml_classifier" (app/classification/
ml_classifier.py) is the ML-ready engine the original spec called
for ("Rule-based initially. ML-ready architecture later.") -- it's
registered here but will raise a clear, actionable error at classify()
time (not at registration/import time) until scripts/train_classifier.py
has actually produced a saved model from enough real corrected
examples. See ml_classifier.py's lazy _load() for why an untrained
model doesn't block this module from importing or registering cleanly.
"""
from app.classification.base import ClassificationEngine
from app.classification.ml_classifier import MLClassifier
from app.classification.rule_based import RuleBasedClassifier
from app.core.exceptions import ValidationFailedException

SUPPORTED_CLASSIFIERS = ("rule_based", "ml_classifier")

_singletons: dict[str, ClassificationEngine] = {}


def get_classification_engine(engine_name: str = "rule_based") -> ClassificationEngine:
    if engine_name not in SUPPORTED_CLASSIFIERS:
        raise ValidationFailedException(
            f"Unknown classification engine '{engine_name}'. "
            f"Supported engines: {list(SUPPORTED_CLASSIFIERS)}"
        )

    if engine_name not in _singletons:
        if engine_name == "rule_based":
            _singletons[engine_name] = RuleBasedClassifier()
        elif engine_name == "ml_classifier":
            _singletons[engine_name] = MLClassifier()

    return _singletons[engine_name]
