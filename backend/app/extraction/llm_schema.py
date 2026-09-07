"""Dynamic Pydantic schema generator for LLM extraction.

Translates domain FieldDef definitions from app.extraction.field_schemas into
runtime Pydantic models with typed fields and field-level metadata for
structured LLM output generation.
"""
from typing import Optional, Type
from pydantic import BaseModel, Field, create_model

from app.extraction.field_schemas import FieldDef, get_full_field_schema


class LLMFieldItem(BaseModel):
    """A single field extracted by the LLM with grounded evidence."""

    value: Optional[str] = Field(
        default=None,
        description="The extracted value as a clean string, or null if not found in the document.",
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Model confidence in the extracted value from 0.0 to 1.0.",
    )
    source_quote: Optional[str] = Field(
        default=None,
        description="Exact verbatim text snippet from the document proving this value.",
    )


def build_dynamic_extraction_model(document_type: str) -> Type[BaseModel]:
    """Dynamically generate a Pydantic model for the given document_type.

    The model fields correspond to all COMMON_FIELDS plus the type-specific
    fields defined in app/extraction/field_schemas.py.
    """
    fields_def: list[FieldDef] = get_full_field_schema(document_type)
    field_definitions: dict[str, tuple[Type, Field]] = {}

    for f in fields_def:
        description = (
            f"Extracted '{f.label}' (field key: '{f.key}', expected data type: {f.field_type})."
        )
        field_definitions[f.key] = (
            Optional[LLMFieldItem],
            Field(default=None, description=description),
        )

    model_name = f"{document_type.upper()}ExtractionPayload"
    DynamicModel = create_model(
        model_name,
        **field_definitions,
        __base__=BaseModel,
    )
    return DynamicModel
