"""
ML-based document classifier.

Loads a scikit-learn pipeline (TF-IDF + LogisticRegression) trained by
scripts/train_classifier.py from accumulated TrainingExample rows.
Implements the same ClassificationEngine interface as RuleBasedClassifier
(app/classification/rule_based.py) -- see app/classification/base.py --
so it's a drop-in swap via the factory with zero router/service changes,
exactly as that interface was designed to allow back in Phase 5.

Lazy-loaded: the joblib file is only read from disk the first time
`classify()` is actually called, not at import time -- mirrors the
lazy-import pattern already used for PaddleOCR/EasyOCR
(app/ocr/paddle_engine.py, app/ocr/easyocr_engine.py), so importing
this module never fails just because no model has been trained yet.
"""
import logging
from pathlib import Path

from app.classification.base import ClassificationEngine, ClassificationResultData
from app.core.exceptions import ValidationFailedException
from app.models.document_enums import DocumentType

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent.parent / "app" / "ml_models" / "classification_model.joblib"


class MLClassifier(ClassificationEngine):
    name = "ml_classifier"

    def __init__(self):
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline

        if not MODEL_PATH.exists():
            raise ValidationFailedException(
                "No trained ML classification model exists yet. Run "
                "scripts/train_classifier.py once enough corrected "
                "examples have accumulated (see that script for the "
                "minimum-data requirements), or use engine=\"rule_based\" "
                "in the meantime."
            )

        import joblib  # deferred import -- consistent with the lazy-load pattern this whole class follows

        logger.info("Loading ML classification model from %s", MODEL_PATH)
        self._pipeline = joblib.load(MODEL_PATH)
        return self._pipeline

    def classify(self, text: str) -> ClassificationResultData:
        pipeline = self._load()

        if not text or not text.strip():
            return ClassificationResultData(
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                engine_name=self.name,
                scores_by_type={},
            )

        predicted_label = pipeline.predict([text])[0]

        # LogisticRegression exposes predict_proba -- use it for a real
        # confidence score and a full scores_by_type breakdown, the
        # same shape RuleBasedClassifier produces, so the API response
        # contract (ClassificationResultResponse) is identical
        # regardless of which engine actually ran.
        classes = pipeline.classes_
        probabilities = pipeline.predict_proba([text])[0]
        scores_by_type = {cls: round(float(prob), 4) for cls, prob in zip(classes, probabilities)}
        confidence = scores_by_type[predicted_label]

        try:
            document_type = DocumentType(predicted_label)
        except ValueError:
            document_type = DocumentType.UNKNOWN

        return ClassificationResultData(
            document_type=document_type,
            confidence=confidence,
            signals=[],  # the ML model doesn't produce human-readable matched signals the way rule_based does
            engine_name=self.name,
            scores_by_type=scores_by_type,
        )
