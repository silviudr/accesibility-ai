"""Validation utilities for client submissions."""

from __future__ import annotations

from pathlib import Path
from typing import List

from src.ingestion.schemas.program_schemas import ProgramSchemaRepository

from .models import (
    ClientSubmission,
    ProgramQuestion,
    ServiceMetadata,
    ValidationIssue,
    ValidationResult,
)
from .repository import ServiceRepository


class ServiceValidator:
    def __init__(self, repository: ServiceRepository, schema_repository: ProgramSchemaRepository | None = None):
        self.repository = repository
        self.schema_repository = schema_repository or ProgramSchemaRepository()

    def validate(self, submission: ClientSubmission) -> ValidationResult:
        issues: List[ValidationIssue] = []
        metadata = self.repository.get_metadata(submission.service_id)
        follow_up_questions: List[Dict[str, str]] = []

        if metadata is None:
            issues.append(
                ValidationIssue(
                    field="service_id",
                    message=f"Service '{submission.service_id}' not found in repository.",
                )
            )
            return ValidationResult(is_valid=False, issues=issues, metadata=None)

        self._validate_language(submission, metadata, issues)
        self._validate_channel(submission, metadata, issues)
        self._validate_identifiers(submission, metadata, issues)
        follow_up_questions = self._validate_program_fields(submission, metadata, issues)

        is_valid = not any(issue.severity == "error" for issue in issues)
        return ValidationResult(is_valid=is_valid, issues=issues, metadata=metadata, follow_up_questions=follow_up_questions)

    def _validate_language(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        issues: List[ValidationIssue],
    ) -> None:
        if submission.preferred_language == "en" and not metadata.service_name_en:
            issues.append(
                ValidationIssue(
                    field="preferred_language",
                    message="English content is not available for this service.",
                )
            )
        if submission.preferred_language == "fr" and not metadata.service_name_fr:
            issues.append(
                ValidationIssue(
                    field="preferred_language",
                    message="French content is not available for this service.",
                )
            )

    def _validate_channel(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        issues: List[ValidationIssue],
    ) -> None:
        normalized = submission.preferred_channel.strip().lower()
        if not normalized:
            issues.append(
                ValidationIssue(
                    field="preferred_channel",
                    message="Preferred channel cannot be empty.",
                )
            )
            return
        if metadata.channels:
            if normalized not in metadata.channels:
                issues.append(
                    ValidationIssue(
                        field="preferred_channel",
                        message=(
                            f"Channel '{submission.preferred_channel}' is not supported. "
                            f"Available: {', '.join(metadata.channels)}"
                        ),
                    )
                )
        else:
            issues.append(
                ValidationIssue(
                    field="preferred_channel",
                    message="Channel metadata is missing for this service.",
                    severity="warning",
                )
            )

    def _validate_identifiers(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        issues: List[ValidationIssue],
    ) -> None:
        if metadata.requires_sin and not submission.sin:
            issues.append(
                ValidationIssue(
                    field="sin",
                    message="This service requires a Social Insurance Number, but none was provided.",
                )
            )
        if metadata.requires_cra and not submission.cra_business_number:
            issues.append(
                ValidationIssue(
                    field="cra_business_number",
                    message="This service requires a CRA business number, but none was provided.",
                )
            )

    def _validate_program_fields(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        issues: List[ValidationIssue],
    ) -> List[ProgramQuestion]:
        schema = self.schema_repository.get(metadata.service_id)
        if not schema:
            return []
        missing_questions: List[ProgramQuestion] = []
        for field in schema.fields:
            answer = submission.program_answers.get(field.key)
            if answer and answer.strip():
                continue
            issues.append(
                ValidationIssue(
                    field=field.key,
                    message=field.prompt_en,
                )
            )
            missing_questions.append(
                ProgramQuestion(
                    key=field.key,
                    type=field.type,
                    label_en=field.label_en,
                    label_fr=field.label_fr,
                    prompt_en=field.prompt_en,
                    prompt_fr=field.prompt_fr,
                    options=field.options or [],
                )
            )
        return missing_questions

def load_default_validator(database_path: Path | str = "data/processed/accessibility_ai.db") -> ServiceValidator:
    repo = ServiceRepository(database_path)
    schema_repo = ProgramSchemaRepository()
    return ServiceValidator(repo, schema_repo)
