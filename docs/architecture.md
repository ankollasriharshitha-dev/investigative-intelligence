# Investigative Intelligence Architecture Notes

## Ownership boundaries

The frontend renders state and invokes service methods. It does not know whether records came from files, uploads, a relational database, Neo4j, or an API.

`InvestigationService` owns application use cases. Future operations such as entity search, relationship search, graph construction, centrality, shortest paths, cross-case associations, suspicious-pattern review, and investigative leads belong here or in focused services called by it.

`DataProvider` owns access to the currently active dataset. Its contract returns source metadata, validation results, and a normalized snapshot. A future `UploadedDataProvider`, `DatabaseDataProvider`, or `ApiDataProvider` can implement the same contract.

## Active source behavior

The provider factory is the single composition point for source selection. It selects `SyntheticDataProvider` or `UploadedDataProvider` from persisted active-source state. An uploaded source becomes active only after validation, normalization, storage, and explicit activation succeed. Services receive that active provider, ensuring downstream analysis cannot silently fall back to synthetic data.

## Dataset contract

CSV tables and JSON documents are storage representations. Services consume `DatasetSnapshot`, not file paths. Entity and relationship schemas should be versioned as the project grows. Stable identifiers are required for future update, deduplication, entity resolution, and relationship upsert operations.

## Daily update path

The intended progression is:

```text
new records -> validate -> normalize -> resolve identifiers -> upsert source
            -> update relationships -> rebuild/update graph -> refresh affected analytics
```

The MVP does not claim real-time processing. Scheduling, persistence, audit logs, authorization, and incremental graph computation belong to later phases.

## Investigation language

Future analytics and UI copy must describe potential connections, network significance, unusual activity, cross-case associations, and items requiring verification. Rule-based prototype signals must not be presented as proof of criminality or as a validated crime-prediction model.

## Document ingestion boundary

Document ingestion is a separate input path, not a second analytics path:

```text
PDF / DOCX / TXT
    -> text extraction
    -> conservative explicit fact extraction
    -> intermediate review representation
    -> validation
    -> human approval
    -> canonical CSV/JSON package
    -> DataManagementService
    -> UploadedDataProvider
    -> graph and analytics
```

The current implementation supports text-based PDF extraction, DOCX paragraphs/tables, and UTF-8 TXT. OCR is not implemented. Extracted records retain document source metadata where the canonical schema permits, and no document-derived records are activated automatically.
