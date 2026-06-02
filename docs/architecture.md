# System Architecture & Workflows

This document details the architectural design, component responsibilities, and runtime workflows of the Enterprise Text-to-SQL API platform.

---

## 1. System Architecture

The platform is designed around a modular, pipeline-oriented architecture implemented in FastAPI. The diagram below illustrates how external clients interact with the API endpoints and how the underlying service layers orchestrate metadata retrieval, LLM query generation, security validation, sandboxed database execution, and caching.

```mermaid
graph TD
    Client[Client / API User] <--> Router[FastAPI Routers /routes/*]
    Router <--> Pipeline[QueryPipeline /services/pipeline.py]
    
    subgraph Service Layer
        Pipeline <--> Retriever[SchemaRetriever /services/retriever.py]
        Pipeline <--> PromptBuilder[SQLPromptBuilder /services/prompt_builder.py]
        Pipeline <--> LLMService[GeminiLLMService /services/llm_service.py]
        Pipeline <--> Validator[SQLValidator /services/validator.py]
        Pipeline <--> Executor[SQLExecutor /services/executor.py]
    end
    
    subgraph Caching & Persistence
        Retriever <--> EmbedStore[Embedding Cache /database/schema_embeddings.json]
        LLMService <--> Cache[BaseCache /services/cache.py]
        Executor <--> SQLite[SQLite Database /database/beaver.db]
    end
    
    subgraph External LLM
        LLMService <--> Gemini[Google Gemini API]
    end
```

---

## 2. Component Workflows

### A. Schema Retrieval Workflow

The Schema Retrieval stage ensures that the LLM is only supplied with schema definitions relevant to the user's natural language question, preserving context limits and minimizing noise.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Router as Retrieval Router
    participant Retriever as SchemaRetriever
    participant EmbedModel as Embedding Model (SentenceTransformer)
    participant Cache as Embeddings Cache (JSON)

    Client->>Router: POST /retrieve {question, top_k}
    Router->>Retriever: retrieve(question, top_k)
    Note over Retriever: Load beaver metadata from schema_metadata.json
    alt Cache is Empty / Fingerprint Mismatch
        Retriever->>EmbedModel: Generate table schema embeddings
        Retriever->>Cache: Save embeddings to schema_embeddings.json
    else Cache Valid
        Retriever->>Cache: Read cached table embeddings
    end
    Retriever->>EmbedModel: encode(question)
    Note over Retriever: Compute cosine similarity between question and table embeddings
    Note over Retriever: Extract Top-K tables
    Note over Retriever: Build dynamic explanations & confidence scores for matched tables
    Retriever-->>Router: list[TableRetrievalResult]
    Router-->>Client: 200 OK (RetrieveResponse)
```

---

## 3. SQL Generation & Validation Loop

Once the relevant tables are identified, the pipeline compiles the schema contexts, selects few-shot examples, generates ANSI-compatible SQL via Gemini, and parses the structured explanation.

```mermaid
sequenceDiagram
    autonumber
    participant Pipeline as QueryPipeline
    participant Builder as SQLPromptBuilder
    participant LLM as GeminiLLMService
    participant Validator as SQLValidator
    participant Gemini as Gemini API (Flash 2.5)

    Pipeline->>Builder: build_prompt(question, retrieved_tables)
    Note over Builder: Formulate system prompt, insert few-shots & schemas
    Builder-->>Pipeline: prompt string
    Pipeline->>LLM: generate(prompt)
    alt Cache Hit
        LLM-->>Pipeline: Cached GenerationResult
    else Cache Miss
        LLM->>Gemini: generate_content(prompt)
        Gemini-->>LLM: JSON text response
        Note over LLM: Strip markdown fences & parse JSON
        Note over LLM: Validate: "sql", "confidence", "explanation" keys
        LLM-->>Pipeline: GenerationResult
    end
    Pipeline->>Validator: validate(sql)
    Note over Validator: Parse AST using SQLGlot (Postgres Dialect)
    Note over Validator: Qualify tables and columns against loaded schema metadata
    Note over Validator: Check table/column existence and permissions
    alt AST Valid
        Validator-->>Pipeline: {"is_valid": true, "errors": []}
    else AST Invalid
        Validator-->>Pipeline: {"is_valid": false, "errors": [...]}
        Note over Pipeline: Raise PipelineValidationError (422 Unprocessable Entity)
    end
```

---

## 4. Sandboxed Query Execution

Queries are executed against the database under strict isolation rules to prevent resource exhaustion and data mutation.

```mermaid
sequenceDiagram
    autonumber
    participant Pipeline as QueryPipeline
    participant Executor as SQLExecutor
    participant SQLite as SQLite (:memory:)
    participant DB as beaver.db (Disk)

    Pipeline->>Executor: execute_query(sql, timeout_seconds)
    Executor->>SQLite: Establish :memory: connection
    Executor->>SQLite: ATTACH 'beaver.db' AS beaver
    Note over Executor: Inject authorizer callback (denies DDL/DML, only SELECT/READ)
    Note over Executor: Inject progress handler callback (checks execution time)
    Executor->>SQLite: execute(sql)
    loop Every VM Instruction
        SQLite->>Executor: progress_handler()
        Note over Executor: Time elapsed > timeout?
        alt Timeout Exceeded
            Executor-->>SQLite: Abort execution (return 1)
            SQLite-->>Executor: sqlite3.OperationalError (interrupted)
            Note over Executor: Raise SQLTimeoutError (408 Timeout)
        else Time OK
            Executor-->>SQLite: Continue (return 0)
        end
    end
    SQLite-->>Executor: Raw Rows & Column headers
    Note over Executor: Format rows into list[dict[col, val]]
    Executor-->>Pipeline: ExecutionResult (rows, columns, row_count, execution_time_ms)
```
