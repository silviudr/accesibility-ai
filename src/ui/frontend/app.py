"""Streamlit UI for the Accessible Communication Assistant POC."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

DEFAULT_API_URL = "http://localhost:8080"
API_BASE_URL = os.getenv("ACCESSIBILITY_API_URL", DEFAULT_API_URL).rstrip("/")


@st.cache_data(show_spinner=False)
def fetch_services() -> List[Dict[str, Any]]:
    response = requests.get(f"{API_BASE_URL}/services", timeout=15)
    response.raise_for_status()
    return response.json()


def validate_submission(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}/validate", json=payload, timeout=30)
    if response.status_code == 404:
        return {"is_valid": False, "issues": [{"field": "service_id", "message": "Service not found."}]}
    response.raise_for_status()
    return response.json()


def run_search(query: str, language: Optional[str], limit: int) -> Dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/search",
        json={"query": query, "language": language or None, "limit": limit},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def run_assist(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}/assist", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


@st.cache_data(show_spinner=False)
def fetch_program_schema(service_id: str) -> Optional[Dict[str, Any]]:
    response = requests.get(f"{API_BASE_URL}/services/{service_id}/schema", timeout=15)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def main() -> None:
    st.set_page_config(page_title="Accessible Communication Assistant", layout="wide")
    st.title("Accessible Communication Assistant (POC)")
    st.caption(f"API base: {API_BASE_URL}")

    try:
        services = fetch_services()
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to load services from API: {exc}")
        st.stop()

    full_options = [
        (
            f"{svc['service_id']} — {svc.get('service_name_en') or svc.get('service_name_fr') or 'Unnamed Service'}",
            svc,
        )
        for svc in services
    ]
    service_filter = st.text_input("Filter services by keyword or ID", placeholder="e.g., horticulture, 125, tribunal")
    if service_filter.strip():
        filtered = [
            option
            for option in full_options
            if service_filter.lower() in option[0].lower()
        ]
        if not filtered:
            st.warning("No services match that filter; showing all services.")
            filtered = full_options
    else:
        filtered = full_options
    service_options = dict(filtered)

    st.subheader("1. Select Service & Review Metadata")
    selected_label = st.selectbox("Service", list(service_options.keys()))
    selected_service = service_options[selected_label]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.write("**Service ID**", selected_service["service_id"])
        st.write("**Channels**", ", ".join(selected_service.get("channels") or ["—"]))
    with col2:
        st.write("**Requires SIN**", "Yes" if selected_service.get("requires_sin") else "No")
        st.write("**Requires CRA #**", "Yes" if selected_service.get("requires_cra") else "No")
    with col3:
        st.write("**Type**", selected_service.get("service_type") or "—")
        st.write("**Scope**", selected_service.get("service_scope") or "—")

    schema_data = None
    if selected_service.get("has_schema"):
        schema_data = fetch_program_schema(selected_service["service_id"])
        if schema_data:
            st.info("This service requires additional program-specific details.")

    program_answers: Dict[str, str] = {}
    if schema_data:
        with st.expander("Program-specific questions", expanded=True):
            for field in schema_data.get("fields", []):
                input_key = f"program_{selected_service['service_id']}_{field['key']}"
                label = field["label_en"]
                field_type = field.get("type", "text")
                if field_type == "select" and field.get("options"):
                    value = st.selectbox(label, options=[""] + field["options"], key=input_key)
                elif field_type == "textarea":
                    value = st.text_area(label, key=input_key)
                else:
                    value = st.text_input(label, key=input_key)
                program_answers[field["key"]] = value

    st.divider()
    st.subheader("2. Validate Client Submission")
    with st.form("validation-form"):
        client_name = st.text_input("Client name", value="Jane Client")
        preferred_language = st.radio("Preferred language", ["en", "fr"], horizontal=True, index=0)
        preferred_channel = st.selectbox(
            "Preferred channel",
            options=selected_service.get("channels") or ["eml", "tel", "onl"],
        )
        contact_email = st.text_input("Contact email", placeholder="client@example.com")
        sin = st.text_input("SIN (if applicable)", max_chars=15)
        cra = st.text_input("CRA Business Number (if applicable)", max_chars=15)
        details = st.text_area("Additional details / accessibility notes")
        submitted = st.form_submit_button("Validate submission")

    validation_result: Optional[Dict[str, Any]] = None
    if submitted:
        payload = {
            "service_id": selected_service["service_id"],
            "client_name": client_name,
            "preferred_language": preferred_language,
            "preferred_channel": preferred_channel,
            "contact_email": contact_email or None,
            "sin": sin or None,
            "cra_business_number": cra or None,
            "additional_details": details or None,
            "program_answers": program_answers,
        }
        with st.spinner("Validating..."):
            try:
                validation_result = validate_submission(payload)
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Validation failed: {exc}")
            else:
                st.success("Submission is valid." if validation_result.get("is_valid") else "Submission has issues.")
                for issue in validation_result.get("issues", []):
                    severity = issue.get("severity", "error").upper()
                    color = "orange" if severity.lower() == "warning" else "red"
                    st.write(f":{color}[{severity}] `{issue.get('field')}` – {issue.get('message')}")
                follow_ups = validation_result.get("follow_up_questions") or []
                if follow_ups:
                    st.warning("Additional information required:")
                    for question in follow_ups:
                        prompt = question.get("prompt_en") if isinstance(question, dict) else question.get("prompt_en")
                        st.write(f"- {prompt}")

    st.divider()
    st.subheader("3. Retrieve Contextual Snippets")
    search_query = st.text_input("Search query", placeholder="Describe what you need...")
    search_language = st.selectbox("Language filter (optional)", options=["Any", "en", "fr"], index=0)
    limit = st.slider("Max results", min_value=1, max_value=10, value=3)
    if st.button("Search"):
        lang_value = None if search_language == "Any" else search_language
        if not search_query.strip():
            st.warning("Enter a query to run semantic search.")
        else:
            with st.spinner("Searching vector store..."):
                try:
                    search_result = run_search(search_query, lang_value, limit)
                except Exception as exc:  # pylint: disable=broad-except
                    st.error(f"Search failed: {exc}")
                else:
                    for idx, hit in enumerate(search_result.get("results", []), start=1):
                        st.markdown(f"**Result {idx}** — distance `{hit.get('distance')}`")
                        st.code(hit.get("document") or "", language="text")
                        st.json(hit.get("metadata") or {})

    st.divider()
    st.subheader("4. LLM Assistance")
    st.write(
        "Combine validation, retrieval, and an Ollama-served LLM to produce a checklist, draft email, "
        "and meeting prep notes. Requires `/assist` API and a running Ollama model."
    )
    assist_query = st.text_input(
        "Assist query (optional)",
        value=" ".join(
            filter(
                None,
                [
                    selected_service.get("service_name_en"),
                    selected_service.get("service_type"),
                    selected_service.get("service_scope"),
                ],
            )
        ),
    )
    assist_lang = st.selectbox("Assist language filter", ["Auto", "en", "fr"], index=0)
    assist_limit = st.slider("Context snippets for LLM", min_value=1, max_value=5, value=3)

    if st.button("Generate assistance"):
        submission_payload = {
            "service_id": selected_service["service_id"],
            "client_name": client_name,
            "preferred_language": preferred_language,
            "preferred_channel": preferred_channel,
            "contact_email": contact_email or None,
            "sin": sin or None,
            "cra_business_number": cra or None,
            "additional_details": details or None,
            "program_answers": program_answers,
        }
        assist_payload = {
            "submission": submission_payload,
            "query": assist_query or None,
            "language": None if assist_lang == "Auto" else assist_lang,
            "limit": assist_limit,
        }
        with st.spinner("Calling /assist..."):
            try:
                assist_result = run_assist(assist_payload)
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Assist call failed: {exc}")
            else:
                validation = assist_result.get("validation", {})
                if not validation.get("is_valid"):
                    st.error("Submission invalid; resolve validation issues first.")
                    for issue in validation.get("issues", []):
                        st.write(f"- `{issue.get('field')}`: {issue.get('message')}")
                    return
                search = assist_result.get("search", {})
                outputs = assist_result.get("outputs") or {}
                with st.expander("Context snippets used by LLM"):
                    for idx, hit in enumerate(search.get("results", []), start=1):
                        label = hit.get("metadata", {}).get("row_identifier") or hit.get("metadata", {}).get("table_name")
                        st.markdown(f"**CTX-{idx}** — {label}")
                        st.code(hit.get("document") or "", language="text")

                st.subheader("Form Checklist")
                checklist = outputs.get("form_checklist") or []
                if checklist:
                    for item in checklist:
                        st.markdown(f"- {item}")
                else:
                    st.write("_No checklist generated._")

                st.subheader("Draft Email")
                st.write(outputs.get("draft_email") or "_No draft email generated._")

                st.subheader("Prep Notes")
                notes = outputs.get("prep_notes") or []
                if notes:
                    for note in notes:
                        st.markdown(f"- {note}")
                else:
                    st.write("_No prep notes generated._")


if __name__ == "__main__":
    main()
