"""
Trains the ML-based document classifier from accumulated
TrainingExample rows (task_type="classification") and saves it to
disk for app/classification/ml_classifier.py to load.

This is a manually-run script, not part of the live request path --
mirrors scripts/seed_users.py's standalone-script pattern. A real
automatic-retraining pipeline (scheduled job, triggered on N new
corrections, etc.) is a deliberately separate, later piece of work;
this script is the first concrete step -- prove the training mechanics
work end-to-end before building automation around them.

HONESTY ABOUT DATA VOLUME: this script enforces a minimum-viable-data
check (MIN_EXAMPLES_PER_CLASS, MIN_CLASSES) and refuses to train below
it, rather than silently producing a model that just always predicts
whichever class happened to have the most examples. A classifier
trained on a handful of examples is not actually useful yet; making
that visible is more valuable than a model that merely runs without
erroring.

Usage:
    python scripts/train_classifier.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import joblib

from app.database.session import get_db_context
from app.repositories.training_example_repository import TrainingExampleRepository

MIN_EXAMPLES_PER_CLASS = 2
MIN_CLASSES = 2
MODEL_DIR = Path(__file__).parent.parent / "app" / "ml_models"
MODEL_PATH = MODEL_DIR / "classification_model.joblib"


def main() -> int:
    with get_db_context() as db:
        repo = TrainingExampleRepository(db)
        counts = repo.count_by_task_and_type("classification")
        examples = repo.list_by_task_type("classification")

    print(f"Found {len(examples)} classification training examples.")
    print(f"Per-class counts: {counts}")
    print()

    classes_with_enough_data = {
        doc_type: count for doc_type, count in counts.items() if count >= MIN_EXAMPLES_PER_CLASS
    }

    if len(classes_with_enough_data) < MIN_CLASSES:
        print(
            f"NOT TRAINING: only {len(classes_with_enough_data)} class(es) have "
            f">= {MIN_EXAMPLES_PER_CLASS} examples each "
            f"(need >= {MIN_CLASSES} such classes to train a meaningful classifier)."
        )
        print(
            "This is expected early on -- the rule-based classifier "
            "(app/classification/rule_based.py) remains the active engine "
            "until enough real corrections accumulate. Re-run this script "
            "periodically as more corrections come in through the UI."
        )
        return 1

    # Only train on examples whose class actually has enough data --
    # a class with a single example would just inject noise (one
    # example can't teach the model anything generalizable about that
    # class, but CAN cause sklearn to misbehave on tiny datasets).
    usable_examples = [e for e in examples if e.document_type in classes_with_enough_data]
    texts = [e.source_text for e in usable_examples]
    labels = [e.document_type for e in usable_examples]

    print(f"Training on {len(usable_examples)} examples across {len(classes_with_enough_data)} classes.")
    print(
        "NOTE: with this little data, no held-out test set is reported -- "
        "any accuracy number from a 1-2-example test split would be "
        "statistically meaningless. Treat this model as experimental "
        "until real-world correction volume grows substantially."
    )

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1)),
        ("classifier", LogisticRegression(max_iter=1000)),
    ])
    pipeline.fit(texts, labels)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)

    print(f"Model saved to {MODEL_PATH}")
    print(
        'To use it, pass {"engine": "ml_classifier"} to'
        "POST /classification/documents/{id}/classify."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
