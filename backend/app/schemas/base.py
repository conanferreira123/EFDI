"""
Shared Pydantic schema base classes.

`BaseSchema` centralizes config (e.g. from_attributes for ORM -> Pydantic
serialization) so every response schema in later phases behaves
consistently without repeating model_config everywhere.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base for all Pydantic schemas. Allows constructing from ORM objects."""
    model_config = ConfigDict(from_attributes=True)


class TimestampSchema(BaseSchema):
    """Mixin schema for models exposing created_at/updated_at."""
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseSchema):
    """Generic simple message response, e.g. for delete/confirmation endpoints."""
    message: str


class HealthCheckResponse(BaseSchema):
    """Response schema for the /health endpoint."""
    status: str
    app_name: str
    environment: str
    database_connected: bool
