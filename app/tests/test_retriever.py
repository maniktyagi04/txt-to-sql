import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import create_app
from app.utils.config import get_settings, Settings
from app.services.retriever import SchemaRetriever, EmbeddedSchemaTable


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Fixture to provide test settings with isolated schema and embedding stores."""
    original_settings = get_settings()

    # We will use the actual schema metadata, but isolate the embedding store JSON
    temp_embedding_store = tmp_path / "test_embeddings.json"

    return Settings(
        app_name="Test Text-to-SQL API",
        app_version="0.1.0-test",
        environment="test",
        debug=True,
        log_level="DEBUG",
        log_format="plain",
        embedding_model_name="all-MiniLM-L6-v2",
        schema_metadata_path=original_settings.schema_metadata_path,
        schema_embedding_store_path=str(temp_embedding_store),
        default_retrieval_top_k=2,
        max_retrieval_top_k=5,
    )


@pytest.fixture
def retriever(test_settings: Settings) -> SchemaRetriever:
    """Fixture to provide an initialized SchemaRetriever instance."""
    return SchemaRetriever(test_settings)


def test_schema_retriever_initialization(
    retriever: SchemaRetriever, test_settings: Settings
):
    """Test that SchemaRetriever initializes settings properly."""
    assert retriever.settings.app_name == "Test Text-to-SQL API"
    assert retriever.settings.environment == "test"
    assert retriever._model is None
    assert retriever._embedded_tables is None


def test_load_schema_metadata(retriever: SchemaRetriever):
    """Test that schema metadata is loaded and validated correctly."""
    tables = retriever._load_schema_metadata()
    assert isinstance(tables, list)
    assert len(tables) > 0
    for table in tables:
        assert table.table_name is not None
        assert isinstance(table.columns, list)
        assert isinstance(table.tags, list)


def test_schema_fingerprint(retriever: SchemaRetriever):
    """Test that schema fingerprint generation is deterministic and unique."""
    tables = retriever._load_schema_metadata()
    fp1 = retriever._schema_fingerprint(tables)
    fp2 = retriever._schema_fingerprint(tables)
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex digest length


def test_build_and_load_embedding_store(
    retriever: SchemaRetriever, test_settings: Settings
):
    """Test that embedding store is built, stored, and then successfully loaded."""
    store_path = Path(test_settings.schema_embedding_store_path)
    assert not store_path.exists()

    # Trigger loading/building
    embedded_tables = retriever._load_or_build_embeddings()
    assert len(embedded_tables) > 0
    assert isinstance(embedded_tables[0], EmbeddedSchemaTable)
    assert (
        len(embedded_tables[0].embedding) == 384
    )  # all-MiniLM-L6-v2 embedding dimension

    # Verify JSON file was created
    assert store_path.exists()
    stored_data = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored_data["model_name"] == "all-MiniLM-L6-v2"
    assert len(stored_data["tables"]) == len(embedded_tables)

    # Re-instantiate retriever to test reading from the cache
    new_retriever = SchemaRetriever(test_settings)
    cached_embedded_tables = new_retriever._load_or_build_embeddings()
    assert len(cached_embedded_tables) == len(embedded_tables)
    assert new_retriever._model is None  # Model is not loaded since it read cache!


def test_semantic_retrieval(retriever: SchemaRetriever):
    """Test semantic retrieval of relevant tables based on natural language questions."""
    # Question about courses should favor courses
    courses_results = retriever.retrieve(
        "What are the credits for course Introduction to Programming?", top_k=2
    )
    assert len(courses_results) == 2
    assert courses_results[0].table_name == "beaver.courses"
    assert courses_results[0].score > 0.0
    assert "course" in courses_results[0].reason.lower() or "beaver" in courses_results[0].reason.lower()

    # Question about student enrollment should favor students or enrollments
    enrollment_results = retriever.retrieve(
        "Show all student enrollments and grades", top_k=1
    )
    assert len(enrollment_results) == 1
    assert "beaver" in enrollment_results[0].table_name
    assert enrollment_results[0].score > 0.0


def test_confidence_score(retriever: SchemaRetriever):
    """Test confidence score calculation is based on the top result."""
    results = retriever.retrieve("student enrollment courses", top_k=2)
    conf = retriever.confidence_score(results)
    assert conf == results[0].score

    assert retriever.confidence_score([]) == 0.0


def test_api_health():
    """Test the health check endpoint."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


def test_api_retrieve_success(test_settings: Settings):
    """Test successful semantic schema retrieval via POST /retrieve."""
    app = create_app()

    # Override settings in app dependency context
    from app.routes.retrieval import get_retriever

    test_retriever = SchemaRetriever(test_settings)
    app.dependency_overrides[get_retriever] = lambda: test_retriever

    with TestClient(app) as client:
        payload = {
            "question": "What is the enrollment year of student Alice Smith?",
            "top_k": 3,
        }
        response = client.post("/retrieve", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert "confidence_score" in data
        assert data["top_k"] == 3
        assert data["model_name"] == "all-MiniLM-L6-v2"

        results = data["results"]
        assert len(results) == 3
        table_names = [r["table_name"] for r in results]
        assert "beaver.students" in table_names
        assert results[0]["score"] > 0.0
        assert isinstance(results[0]["reason"], str)


def test_api_retrieve_validation_errors():
    """Test API input validation handling for POST /retrieve."""
    app = create_app()
    with TestClient(app) as client:
        # Question too short (min length is 3)
        response = client.post("/retrieve", json={"question": "hi", "top_k": 2})
        assert response.status_code == 422

        # Missing question
        response = client.post("/retrieve", json={"top_k": 2})
        assert response.status_code == 422

        # Invalid top_k
        response = client.post(
            "/retrieve", json={"question": "Valid question text", "top_k": -1}
        )
        assert response.status_code == 422
