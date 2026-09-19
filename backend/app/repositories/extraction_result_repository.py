"""
ExtractionResult repository: data-access layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction_result import ExtractionResult


class ExtractionResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, extraction_result_id: int) -> ExtractionResult | None:
        return self.db.get(ExtractionResult, extraction_result_id)

    def get_latest_for_document(self, document_id: int) -> ExtractionResult | None:
        stmt = (
            select(ExtractionResult)
            .where(ExtractionResult.document_id == document_id)
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_document(self, document_id: int) -> list[ExtractionResult]:
        stmt = (
            select(ExtractionResult)
            .where(ExtractionResult.document_id == document_id)
            .order_by(ExtractionResult.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        document_type: str,
        engine_name: str,
        fields: dict,
        overall_confidence: float,
        fields_found_count: int,
        fields_total_count: int,
    ) -> ExtractionResult:
        result = ExtractionResult(
            document_id=document_id,
            document_type=document_type,
            engine_name=engine_name,
            fields=fields,
            overall_confidence=overall_confidence,
            fields_found_count=fields_found_count,
            fields_total_count=fields_total_count,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def update_field(self, extraction_result: ExtractionResult, field_key: str, value: str) -> ExtractionResult:
        """
        Manually correct/fill a single field, marking it as
        human-entered (confidence 1.0, no matched_text since it wasn't
        OCR-matched). Mutates the JSONB fields dict in place.
        For NPO documents, keeps canonical dot-paths, root canonical dictionary,
        and flat legacy aliases synchronized.
        """
        from app.extraction.field_schemas import map_npo_canonical_to_flat, map_npo_flat_to_canonical

        fields = dict(extraction_result.fields)
        field_payload = {
            "value": value,
            "confidence": 1.0,
            "matched_text": None,
            "is_found": True,
            "manually_entered": True,
            "provenance": "manual",
        }
        fields[field_key] = field_payload

        # Synchronize dual canonical and flat keys for NPO
        if extraction_result.document_type == "NPO":
            canon_path = map_npo_flat_to_canonical(field_key)
            flat_key = map_npo_canonical_to_flat(field_key)

            if canon_path != field_key:
                fields[canon_path] = field_payload
            if flat_key != field_key:
                fields[flat_key] = field_payload

            # Update root canonical dictionary if present
            if "canonical" in fields and isinstance(fields["canonical"].get("value"), dict):
                canon_dict = dict(fields["canonical"]["value"])
                if "." in canon_path:
                    sec, leaf = canon_path.split(".", 1)
                    if sec in canon_dict and isinstance(canon_dict[sec], dict):
                        canon_dict[sec] = dict(canon_dict[sec])
                        canon_dict[sec][leaf] = field_payload
                        fields["canonical"] = dict(fields["canonical"])
                        fields["canonical"]["value"] = canon_dict

        extraction_result.fields = fields

        found_count = sum(1 for f in fields.values() if isinstance(f, dict) and f.get("is_found"))
        extraction_result.fields_found_count = found_count

        self.db.commit()
        self.db.refresh(extraction_result)
        return extraction_result
