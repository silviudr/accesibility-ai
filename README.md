# Accessible Communication Assistant

## Problem Statement
Clients have a wide variety of communication needs, and interactions with the government can be challenging, frustrating, and can exacerbate existing barriers. We must design a solution that communicates with people in a way that is accessible to a wide range of languages, cultures, and abilities.

### Additional Context
The solution should:
1. Ingest and verify information provided by a client.
2. Request additional information from the client depending on the program they are applying to or inquiring about.
3. Assist with pulling the relevant information together so clients can fill out forms, draft emails, or prepare for discussions with government representatives or similar contacts.

## Available Data (sampled via `dataset_samples.txt`)
- **Service inventory** with bilingual descriptions, client types, supported channels, accessibility flags, and web references.
- **Program financials and FTE plans** (`rbpo_rppo_*.csv`) capturing planned vs. actual spend plus variance explanations for each core responsibility/program.
- **Performance indicators** (`pipo_irpo_*.csv`) containing result statements, indicator definitions, baseline and methodology text useful for grounding responses.
- **Appropriations/expenditures tables** (`abv_apc_*`, `eav_eac_*`, `eso_eac_*`) providing fiscal authorities that can support generated summaries or rationales.
- **Service standards** (`service-std.csv`, `service_standards_2018-2023.csv`) outlining SLA targets, performance figures, and bilingual links for transparency in client guidance.

## High-Level Architecture
1. **Data Ingestion & Normalization** (`src/ingestion/`)
   - ETL pipelines load the bilingual CSVs under `datasets/`, align schemas, and publish structured tables plus embeddings for unstructured descriptions.
2. **Knowledge & Storage Layer** (`src/services/knowledge/`)
   - Stores normalized program metadata, service schemas, SLA metrics, and the vector index used by retrieval-augmented generation.
3. **Language & Accessibility Services** (`src/services/language/`)
   - Provides language detection, translation, text-to-speech, and speech-to-text utilities to keep the rest of the stack language-agnostic.
4. **Intake & Validation Engine** (`src/services/validation/`)
   - Applies program-specific schemas (via pydantic) to client submissions, returning structured validation errors or normalized payloads.
5. **Adaptive Dialogue Module** (`src/services/dialogue/`)
   - Manages conversational state, crafts follow-up questions for missing data, and records an auditable trace of prompts/responses.
6. **Assistive Generation Engine** (`src/services/generation/`)
   - Runs retrieval-augmented prompts that assemble form-fill checklists, draft correspondence, and meeting prep notes, citing source data.
7. **API Gateway** (`src/services/api/`)
   - FastAPI layer that orchestrates language services, validation, retrieval, and generation for both the UI and external consumers.
8. **User Experience Layer** (`src/ui/frontend/`)
   - Accessibility-first Streamlit/Gradio client offering multi-language intake forms, adaptive questioning, and exportable outputs.
9. **Observability & Logging** (`src/services/logging/`)
   - Centralizes telemetry for translations, validations, and generations, ensuring compliance and debugging support.

## Repository Layout
```
src/
  ingestion/               # ETL pipelines and schemas for datasets
  services/
    api/                   # FastAPI gateway + routing
    language/              # Translation, ASR/TTS utilities
    validation/            # Program schemas and validation logic
    dialogue/              # State machine / conversation orchestration
    generation/            # Retrieval-augmented generation workflows
    knowledge/             # Data access, vector store connectors
    logging/               # Structured logging and observability hooks
  ui/
    frontend/              # Streamlit or Gradio client
config/                    # Environment and pipeline config (samples under config/samples)
datasets/                  # Source CSVs referenced by the ETL
util-scripts/              # Helper scripts (e.g., dataset sampler)
docs/
  architecture/            # Detailed design notes, diagrams, ADRs
venv/                      # (optional) local virtual environment placeholder
tests/                     # Pytest modules grouped by subsystem
```

## ETL Usage
Run the ingestion pipeline to populate a local SQLite database with the CSV contents:

```bash
python3 src/ingestion/pipelines/load_datasets.py \
  --datasets datasets \
  --database data/processed/accessibility_ai.db \
  --verbose
```

This script:
- Normalizes each column/table name before storing.
- Loads every CSV file in `datasets/` into SQLite (one table per file).
- Records metadata (source path, column names, row counts, ingestion timestamp) in the `data_sources` table.

## Vector Store Usage
After the SQLite database is populated, create a persistent Chroma store with embeddings for **every** table in the database:

```bash
python3 src/ingestion/pipelines/build_vector_store.py \
  --database data/processed/accessibility_ai.db \
  --persist-dir data/vectorstore \
  --collection accessible_services \
  --reset
```

The script inspects every table (excluding `data_sources` and SQLite internals), builds per-row documents, and automatically creates language-specific entries whenever column names follow `_en/_fr` naming conventions. Use `--tables <table_name ...>` to limit ingestion to a subset. The first run downloads the `sentence-transformers/all-MiniLM-L6-v2` model (ensure the environment has access to it).

## Validation Service Usage
The validation layer loads service metadata from SQLite and checks client submissions for:
- valid `service_id`
- language availability (English/French)
- supported communication channels
- required identifiers (SIN or CRA numbers) inferred from datasets

Run the helper script to test validations from the CLI:

```bash
python3 util-scripts/validate_submission.py \
  125 \"Jane Client\" en email \
  --email jane@example.com \
  --sin 123456789
```

The script prints a JSON payload containing `is_valid`, any `issues`, and the service metadata snapshot that drove the decision. Integrate the underlying classes from `src/services/validation/` into the FastAPI layer to power UI/API flows.

## FastAPI Service
A lightweight FastAPI app lives in `src/services/api/main.py`, exposing:
- `GET /services` — list service metadata (channels, identifier requirements)
- `POST /validate` — validate a `ClientSubmission` payload
- `POST /search` — semantic search over the Chroma vector store
- `POST /assist` — validate, retrieve context, and call an Ollama-served LLM to produce form checklists, draft emails, and prep notes

Run it locally with uvicorn:

```bash
uvicorn src.services.api.main:app --reload --port 8080
```

Once running, you can query `http://localhost:8080/services`, post submissions to `/validate`, or send `{ "query": "...", "language": "en" }` to `/search` to retrieve contextual snippets from the datasets.

The `/assist` endpoint expects an Ollama instance listening at `OLLAMA_BASE_URL` (defaults to `http://localhost:11434`) with a model such as `mixtral` pulled locally. Configure different values via the `OLLAMA_BASE_URL` / `OLLAMA_MODEL` environment variables before launching uvicorn.

Example request:

```bash
curl -s -X POST http://localhost:8080/assist \
  -H "Content-Type: application/json" \
  -d '{
        "submission": {
          "service_id": "125",
          "client_name": "Jane Client",
          "preferred_language": "en",
          "preferred_channel": "eml"
        },
        "query": "horticulture market information service standards",
        "language": "en",
        "limit": 3
      }' | jq
```

## Streamlit UI
A lightweight Streamlit dashboard (`src/ui/frontend/app.py`) calls the API to:
- filter/select services and inspect their metadata,
- view program-specific schemas and capture adaptive answers,
- validate submissions (showing any follow-up questions),
- run semantic searches and inspect retrieved snippets,
- generate LLM-assisted checklists/emails/notes (using `/assist` + Ollama).

Launch it (with the FastAPI service already running) via:

```bash
streamlit run src/ui/frontend/app.py
```

Override the API base URL by setting `ACCESSIBILITY_API_URL` before launching if needed.

## Next Steps
1. **Define program schemas** under `src/ingestion/schemas/` and expose them through the validation service.
2. **Scaffold the FastAPI gateway** (`src/services/api/`) with endpoints for language detection, validation, adaptive questioning, and assistive output generation.
3. **Prototype the UI** in `src/ui/frontend/` to exercise the API, show bilingual guidance, and surface accessibility cues from the data.
4. **Add automated tests** in `tests/` covering ETL integrity, schema validation, and API contract checks.

Document new assumptions and decisions in `docs/architecture/` as the implementation progresses.

## License
This project is provided solely for evaluation in the G7 GovAI Grand Challenge under the terms described in [LICENSE](LICENSE). Unauthorized use is prohibited.
