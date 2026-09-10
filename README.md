# INVESTIGATIVE INTELLIGENCE

Criminal Network Analysis Platform · SIH 2026 • PS 26189

This is a SIH-ready investigative intelligence MVP for Problem Statement 26189. It combines a professional frontend, validated synthetic/uploaded data workflows, a provider/service architecture, graph analytics, explainable investigative leads, and local dynamic-update foundations. The product remains deliberately separated from the current data source so future uploaded, database-backed, or API-backed investigations can use the same frontend and service contracts.

## Run locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

## Architecture

```text
Streamlit UI (ui/)
        |
Investigation services (services/)
        |
DataProvider interface (providers/base.py)
        |
SyntheticDataProvider (providers/synthetic.py)
        |
data/synthetic/ structured files
```

The UI never reads CSV or JSON files directly. `InvestigationService` is the application boundary, and `DataProvider` is the replaceable storage boundary. The current provider validates and loads the external synthetic files into a normalized `DatasetSnapshot`.

## Data sources

- `data/synthetic/` is the isolated Synthetic Demo Dataset. It contains fictional entities, cases, and relationship records only.
- `data/uploads/` is reserved for future user-provided datasets and is ignored by git except for its directory marker.
- The provider factory is the composition point where an uploaded, database-backed, or API provider can become active. Once selected there, all service operations will use that provider.

## Extension path

The future import workflow should validate CSV/JSON input, normalize it into the domain schema, and apply an explicit replace/append/update operation. It should then register the uploaded source as active and trigger graph and analytics refreshes through services. Daily updates can use the same interface with stable entity identifiers, deduplication, relationship upserts, and incremental or full recomputation as appropriate.

The current provider validates required files, columns, unique identifiers, timestamps, case references, and relationship endpoints before the dashboard displays statistics. NetworkX, stronger NLP/NER, Neo4j, persistent databases, APIs, and production frontends can be introduced behind these boundaries without embedding today's synthetic source into the UI.

## Verification

```powershell
python -m pytest -q
python -c "from config.settings import get_settings; from providers.synthetic import SyntheticDataProvider; p = SyntheticDataProvider(get_settings().synthetic_data_dir); print(p.validate())"
```

## Graph capabilities

The active snapshot is converted by `graph/builder.py` into a typed NetworkX graph. `graph/analytics.py` calculates degree centrality, betweenness, PageRank, connected components, shortest paths, two-hop and three-hop connections, cross-case associations, and transparent potential investigative leads. All graph requests rebuild from the current provider snapshot, so a future active provider replacement will flow through the same service interface.

`graph/investigative.py` adds closeness centrality, a transparent weighted Network Significance score, community detection, communication activity, transaction activity, location associations, vehicle associations, cross-case signals, and a prioritized lead engine. The score is a presentation heuristic, not a validated risk or criminality score.

The UI exposes network filters, entity inspection, connection analysis, key-entity rankings, cluster summaries, cross-case associations, searchable entity evidence, and filtered heuristic leads. Signals are labeled `Requires Verification` and are not claims of guilt or criminality.

## Data management

The Data Management workspace accepts a complete structured package of the current internal schema: `persons.csv`, `phones.csv`, `calls.csv`, `messages.csv`, `transactions.csv`, `locations.csv`, `vehicles.csv`, `organizations.csv`, `accounts.csv`, `events.csv`, and `cases.json`. CSV and JSON files are validated for columns, IDs, timestamps, case references, and relationship endpoints before deterministic normalization and storage.

The workflow is explicit: upload and preview, validate, import as a staged package, then activate. Uploaded files are stored under `data/uploads/current/`; the synthetic dataset under `data/synthetic/` is never modified. The active source is persisted in `data/uploads/.active_source.json`, and the provider factory composes either `SyntheticDataProvider` or `UploadedDataProvider` on the next request/startup. Replace, append, update, clear, source switching, and lightweight upload history are supported. Clearing uploaded data switches back to the synthetic provider.

For a reproducible demonstration, the smaller fictional package under `data/test_upload/` contains 5 persons, 4 phones, 1 case, and a smaller relationship set. It is used by the source-switch regression tests and can be selected in the Data Management upload control.

## Dynamic-data foundation

`repositories/base.py` defines a persistence boundary for file, SQL, or API repositories. `repositories/local.py` is the current local adapter. `graph/provider.py` defines the graph boundary; `NetworkXGraphProvider` is the current implementation and a future Neo4j provider can satisfy the same contract.

Uploaded dataset metadata is tracked in `data/uploads/dataset_metadata.json` with a dataset ID, revision, source, timestamps, record count, status, and validation status. Operations create structured ingestion records in `data/uploads/upload_history.json` with ingestion ID, operation, timestamp, received/added/updated/rejected counts, status, and revision.

`services/ingestion.py` provides a local development/daily-update facade for validated append and update packages. The current implementation is deliberately local and synchronous. It models ingestion, validation, normalization, deduplication, upsert, provider refresh, graph refresh, and analytics refresh without pretending to be real-time infrastructure.

Security boundaries, authentication, authorization, encryption, retention policy, production audit controls, database persistence, Neo4j, and backend API deployment remain future production work.

## SIH demo readiness

Recommended demonstration flow:

```text
Overview
        -> Cases
        -> Investigation Network
        -> Entity Explorer
        -> Network Analysis
        -> Investigative Leads
        -> Data Management
        -> upload data/test_upload/
        -> validate
        -> import
        -> activate
        -> show changed dashboard, graph, analytics, and leads
        -> clear uploaded data
        -> confirm Synthetic Demo Dataset is restored
```

The final acceptance lifecycle is covered by the automated suite: synthetic mode loads first, the smaller test package is validated and activated, all downstream graph/analytics counts change, a daily append increments the dataset revision, and clearing uploaded data restores the original synthetic provider and graph.

This project is positioned as a SIH-ready investigative intelligence MVP with modular extension points for a production backend, database, graph database, AI/ML services, and real or anonymized data integration. It is not production-secure and does not claim live law-enforcement feeds, validated criminality prediction, authentication, authorization, or enterprise audit controls.

## Document ingestion

Structured data continues to use the existing complete CSV/JSON package uploader. A separate Data Management path accepts PDF, DOCX, and UTF-8 TXT documents. `services/document_ingestion.py` extracts text and conservative, explicitly structured facts; it does not claim production NLP, OCR, forensic evidence preservation, or automatic guilt inference.

Document records are shown for review before approval. `Approve & Add to Investigation Dataset` converts approved facts into the same canonical CSV/JSON package and calls the existing `DataManagementService` pipeline. `Discard` prevents extracted facts from entering the dataset. Source lineage is retained through `source_type`, `source_file`, and `source_case` columns where the current schema permits.

Text-based PDFs are supported through `pypdf`. If a PDF has no extractable text, the application reports that OCR support is planned for a future production version. DOCX extraction uses `python-docx` paragraphs and table rows. The synthetic fixture [data/test_documents/northbridge_college_ci_2026_0047.docx](data/test_documents/northbridge_college_ci_2026_0047.docx) is clearly marked as a training document and is not automatically activated.

Document ingestion is intended for synthetic or anonymized development data in this prototype. Production deployment requires appropriate access control, encryption, audit logging, retention policies, privacy safeguards, stronger validation, and human review.

## Windows upload cleanup

Uploaded dataset replacement and clearing use a Python filesystem helper that safely handles missing paths, read-only file attributes, and short-lived Windows/OneDrive locks with bounded retries. If the directory remains locked, the operation raises a storage error and the UI asks the investigator to close applications using the dataset; it does not switch the active source or report success until deletion completes.
