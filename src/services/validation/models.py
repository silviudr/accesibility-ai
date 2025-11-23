"""Pydantic models used by the validation service."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class ServiceMetadata(BaseModel):
    service_id: str
    service_name_en: Optional[str] = None
    service_name_fr: Optional[str] = None
    department_name_en: Optional[str] = None
    department_name_fr: Optional[str] = None
    service_type: Optional[str] = None
    service_scope: Optional[str] = None
    client_target_groups: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    requires_sin: bool = False
    requires_cra: bool = False
    fiscal_year: Optional[str] = None


class ClientSubmission(BaseModel):
    service_id: str = Field(..., description="Identifier of the service/program the client is targeting.")
    preferred_language: Literal["en", "fr"] = Field(
        ..., description="Client's preferred language for communication (en or fr)."
    )
    preferred_channel: str = Field(..., description="Desired communication channel (email, phone, online, etc.)")
    client_name: str = Field(..., min_length=1, description="Client's name for contextual personalization.")
    contact_email: Optional[EmailStr] = Field(
        default=None, description="Email address if the client wants digital correspondence."
    )
    sin: Optional[str] = Field(
        default=None,
        description="Social Insurance Number provided when the service explicitly requires it.",
    )
    cra_business_number: Optional[str] = Field(
        default=None,
        description="CRA business number supplied for services that rely on organization identifiers.",
    )
    additional_details: Optional[str] = Field(
        default=None, description="Free text payload containing extra goals, accessibility notes, etc."
    )
    program_answers: Dict[str, str] = Field(
        default_factory=dict,
        description="Answers to program-specific adaptive questions keyed by schema field.",
    )


class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


class ProgramQuestion(BaseModel):
    key: str
    type: str = "text"
    label_en: str
    label_fr: str
    prompt_en: str
    prompt_fr: str
    options: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    is_valid: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    metadata: Optional[ServiceMetadata] = None
    follow_up_questions: List[ProgramQuestion] = Field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]
