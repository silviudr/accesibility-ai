"""LLM assistant that calls an Ollama endpoint to produce structured assistance."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from src.services.validation.models import ClientSubmission, ServiceMetadata

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "mixtral"


class LLMAssistant:
    """Thin wrapper around Ollama's /api/generate endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_URL).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL

    def build_prompt(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        search_hits: List[Dict[str, Any]],
    ) -> str:
        context_lines: List[str] = []
        context_lines.append("Service metadata:")
        context_lines.append(f"- ID: {metadata.service_id}")
        context_lines.append(f"- Name (EN): {metadata.service_name_en}")
        context_lines.append(f"- Name (FR): {metadata.service_name_fr}")
        context_lines.append(f"- Channels: {', '.join(metadata.channels) if metadata.channels else 'N/A'}")
        context_lines.append(f"- Requires SIN: {metadata.requires_sin}")
        context_lines.append(f"- Requires CRA: {metadata.requires_cra}")
        context_lines.append(f"- Type: {metadata.service_type}")
        context_lines.append(f"- Scope: {metadata.service_scope}")

        context_lines.append("\nTop retrieved context snippets (cite by ID):")
        for idx, hit in enumerate(search_hits, start=1):
            metadata_id = hit.get("metadata", {}).get("row_identifier") or hit.get("metadata", {}).get("table_name")
            context_lines.append(f"[CTX-{idx} | {metadata_id}]\n{hit.get('document', '')}\n")

        instructions = (
            "You are assisting an intake specialist who helps clients engage with government services. "
            "Use the context above to produce JSON with the following keys:\n"
            "{\n"
            '  "form_checklist": [ "bullet 1 [CTX-1]", "bullet 2 ..." ],\n'
            '  "draft_email": "Paragraphs... include greeting and closing.",\n'
            '  "prep_notes": [ "note 1 [CTX-3]", "note 2 ..." ]\n'
            "}\n"
            "The checklist and notes should be concise (max 5 items each). "
            "The draft email must be in the client's preferred language and include the service name. "
            "Cite supporting snippets using [CTX-n] notation. If information is missing, be transparent."
        )

        client_desc = (
            f"Client name: {submission.client_name}\n"
            f"Preferred language: {submission.preferred_language}\n"
            f"Preferred channel: {submission.preferred_channel}\n"
            f"Additional details: {submission.additional_details or 'N/A'}"
        )

        prompt = f"{instructions}\n\nClient details:\n{client_desc}\n\n{os.linesep.join(context_lines)}"
        return prompt

    def generate(
        self,
        submission: ClientSubmission,
        metadata: ServiceMetadata,
        search_hits: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prompt = self.build_prompt(submission, metadata, search_hits)
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("response") or ""

        return {
            "raw_prompt": prompt,
            "raw_response": text.strip(),
        }

