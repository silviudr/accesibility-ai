"""FastAPI application exposing validation and semantic search endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.services.generation.assistant import LLMAssistant
from src.ingestion.schemas.program_schemas import ProgramSchemaRepository
from src.services.knowledge.vector_search import VectorSearcher
from src.services.validation.models import ClientSubmission, ServiceMetadata, ValidationResult
from src.services.validation.repository import ServiceRepository
from src.services.validation.validator import ServiceValidator

DATABASE_PATH = Path("data/processed/accessibility_ai.db")
VECTOR_DIR = Path("data/vectorstore")
COLLECTION_NAME = "accessible_services"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

repository = ServiceRepository(DATABASE_PATH)
schema_repository = ProgramSchemaRepository()
validator = ServiceValidator(repository, schema_repository)
searcher = VectorSearcher(VECTOR_DIR, COLLECTION_NAME, EMBEDDING_MODEL)
assistant = LLMAssistant()

app = FastAPI(
    title="Accessibility AI API",
    version="0.1.0",
    description="POC API for validation and semantic retrieval over accessibility datasets.",
)


class ServiceSummary(BaseModel):
    service_id: str
    service_name_en: Optional[str] = None
    service_name_fr: Optional[str] = None
    service_type: Optional[str] = None
    service_scope: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    requires_sin: bool = False
    requires_cra: bool = False
    has_schema: bool = False

    @classmethod
    def from_metadata(cls, metadata: ServiceMetadata) -> "ServiceSummary":
        return cls(
            service_id=metadata.service_id,
            service_name_en=metadata.service_name_en,
            service_name_fr=metadata.service_name_fr,
            service_type=metadata.service_type,
            service_scope=metadata.service_scope,
            channels=metadata.channels,
            requires_sin=metadata.requires_sin,
            requires_cra=metadata.requires_cra,
            has_schema=schema_repository.get(metadata.service_id) is not None,
        )


class SearchRequest(BaseModel):
    query: str = Field(..., description="Free text query to run against the vector store.")
    language: Optional[str] = Field(
        default=None,
        description="Optional language filter (e.g., 'en' or 'fr') applied to metadata when querying.",
    )
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of semantic hits to return.")


class SearchHit(BaseModel):
    document: str
    metadata: Dict[str, Any]
    distance: Optional[float] = None


class SearchResponse(BaseModel):
    query: str
    results: List[SearchHit]


class AssistRequest(BaseModel):
    submission: ClientSubmission
    query: Optional[str] = Field(
        default=None,
        description="Optional custom semantic search query. Defaults to service name and type.",
    )
    language: Optional[str] = Field(
        default=None,
        description="Language filter for retrieval. Defaults to submission preferred language.",
    )
    limit: int = Field(default=3, ge=1, le=10, description="Number of context snippets to retrieve.")


class AssistOutputs(BaseModel):
    form_checklist: List[str] = Field(default_factory=list)
    draft_email: str = ""
    prep_notes: List[str] = Field(default_factory=list)
    raw_response: str = ""


class AssistResponse(BaseModel):
    validation: ValidationResult
    search: SearchResponse
    outputs: Optional[AssistOutputs] = None


class ProgramFieldResponse(BaseModel):
    key: str
    type: str
    label_en: str
    label_fr: str
    prompt_en: str
    prompt_fr: str
    options: List[str] = Field(default_factory=list)


class ProgramSchemaResponse(BaseModel):
    service_id: str
    fields: List[ProgramFieldResponse]


@app.get("/services", response_model=List[ServiceSummary])
def list_services() -> List[ServiceSummary]:
    """Return the current catalog of services with channel/identifier metadata."""
    services = repository.list_services()
    return [ServiceSummary.from_metadata(metadata) for metadata in services]


@app.post("/validate", response_model=ValidationResult)
def validate_submission(submission: ClientSubmission) -> ValidationResult:
    """Validate a client submission against service metadata."""
    result = validator.validate(submission)
    if result.metadata is None:
        raise HTTPException(status_code=404, detail="Service not found.")
    return result


@app.post("/search", response_model=SearchResponse)
def semantic_search(request: SearchRequest) -> SearchResponse:
    """Run a semantic search against the Chroma vector store."""
    hits = searcher.search(query=request.query, language=request.language, limit=request.limit)
    return SearchResponse(
        query=request.query,
        results=[SearchHit(**hit) for hit in hits],
    )


@app.get("/services/{service_id}/schema", response_model=ProgramSchemaResponse)
def get_program_schema(service_id: str) -> ProgramSchemaResponse:
    schema = schema_repository.get(service_id)
    if not schema:
        raise HTTPException(status_code=404, detail="No program schema for this service.")
    fields = [
        ProgramFieldResponse(
            key=field.key,
            type=field.type,
            label_en=field.label_en,
            label_fr=field.label_fr,
            prompt_en=field.prompt_en,
            prompt_fr=field.prompt_fr,
            options=field.options or [],
        )
        for field in schema.fields
    ]
    return ProgramSchemaResponse(service_id=service_id, fields=fields)


@app.post("/assist", response_model=AssistResponse)
def assist(request: AssistRequest) -> AssistResponse:
    """Validate the submission, retrieve context, and run the LLM assistant via Ollama."""
    validation = validator.validate(request.submission)
    if validation.metadata is None:
        raise HTTPException(status_code=404, detail="Service not found.")

    # If validation failed, return issues without invoking the model.
    if not validation.is_valid:
        empty_search = SearchResponse(query=request.query or "", results=[])
        return AssistResponse(validation=validation, search=empty_search, outputs=None)

    search_query = request.query or " ".join(
        filter(
            None,
            [
                validation.metadata.service_name_en,
                validation.metadata.service_type,
                validation.metadata.service_scope,
            ],
        )
    )
    language = request.language or request.submission.preferred_language
    hits = searcher.search(query=search_query, language=language, limit=request.limit)
    search_response = SearchResponse(
        query=search_query,
        results=[SearchHit(**hit) for hit in hits],
    )

    try:
        generation = assistant.generate(request.submission, validation.metadata, hits)
        parsed = json.loads(generation.get("raw_response", "{}"))
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}") from exc

    outputs = AssistOutputs(
        form_checklist=parsed.get("form_checklist") or [],
        draft_email=parsed.get("draft_email") or generation.get("raw_response", ""),
        prep_notes=parsed.get("prep_notes") or [],
        raw_response=generation.get("raw_response", ""),
    )

    return AssistResponse(
        validation=validation,
        search=search_response,
        outputs=outputs,
    )
