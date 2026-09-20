from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standard_installer_waits_for_neo4j_and_runs_full_schema_upgrade():
    script = (ROOT / "install/profiles/install-standard.sh").read_text()
    start = script.index('compose_cmd -f docker-compose.yml --env-file .env "${LOCAL_PROFILE_ARGS[@]}" up -d')
    init = script.index('"$PREFIX/.venv/bin/python" -m rag.graph --config "$PREFIX/config.yaml" init')
    assert init > start
    assert 'if [[ $WITH_NEO4J -eq 1 ]]' in script[start:init]
    assert 'NEO4J_PASSWORD="$NEO4J_PASSWORD"' in script[start:init + 500]
    assert "NEO4J_SCHEMA_READY" in script[start:init + 1000]
    assert "exit 1" in script[init:init + 1200]


def test_super_light_installer_waits_for_neo4j_and_retries_schema_upgrade():
    script = (ROOT / "install/profiles/install-super-light.sh").read_text()
    stack_start = script.index('compose up -d --remove-orphans "${SERVICES[@]}"')
    init = script.index("compose exec -T api python -m rag.graph --config /app/config.yaml init")
    assert init > stack_start
    window = script[stack_start:init + 1200]
    assert "NEO4J_SCHEMA_READY=0" in window
    assert "for attempt in $(seq 1 90)" in window
    assert "Neo4j/schema: waiting" in window
    assert "Neo4j/schema: ready" in script[init:init + 1800]
    assert "Neo4j did not become ready or the AKI schema upgrade failed." in window
    assert "sleep 2" in window
    assert "exit 1" in window


def test_api_startup_has_nonfatal_schema_upgrade_fallback():
    api = (ROOT / "rag/api.py").read_text()
    assert "def _initialize_neo4j_schema()" in api
    assert "graph.ensure_schema()" in api
    assert "_initialize_neo4j_schema()" in api
    assert "Neo4j schema initialization deferred" in api
