"""Tests for the production Docker Compose configuration.

Validates that infra/docker-compose.prod.yml and deploy rollout contracts:
- Parses without errors via both PyYAML and `docker compose config`
- Declares exactly 4 services: db, api, web, caddy
- Only caddy (public ingress) may bind host ports to all interfaces
- api and web declare depends_on with health check conditions
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import yaml
import pytest
from pathlib import Path

from api.health_content import FEDERAL_FIRST_CONTENT_FLOORS
import core.keel_gate_l13 as keel_gate_l13

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.prod.yml"
API_DOCKERFILE_FILE = REPO_ROOT / "infra" / "api" / "Dockerfile"
DEPLOY_WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
BOOTSTRAP_SCRIPT_FILE = REPO_ROOT / "infra" / "scripts" / "bootstrap_prod_vm.sh"
AGE_BOOTSTRAP_SQL_FILE = REPO_ROOT / "infra" / "db" / "09-age-graph-bootstrap.sql"
CADDYFILE_FILE = REPO_ROOT / "infra" / "Caddyfile"
PROD_COMPOSE_WRAPPER_FILE = REPO_ROOT / "infra" / "scripts" / "prod_compose.sh"
# Must match the volumes list in infra/docker-compose.prod.yml exactly.
# nc_orchestrator was added to prod but the expected list in this test was
# never updated — that drift caused the pre-Apr 30 CI red run that masked
# everything else; now keep them aligned.
_EXPECTED_DB_INIT_MOUNTS = [
    "../core/schema/entities.sql:/docker-entrypoint-initdb.d/01-entities.sql",
    "../core/schema/jurisdiction.sql:/docker-entrypoint-initdb.d/02-jurisdiction.sql",
    "../core/schema/provenance.sql:/docker-entrypoint-initdb.d/03-provenance.sql",
    "../core/schema/entity_resolution.sql:/docker-entrypoint-initdb.d/04-entity_resolution.sql",
    "../core/schema/er_views.sql:/docker-entrypoint-initdb.d/05-er_views.sql",
    "../domains/campaign_finance/schema/tables.sql:/docker-entrypoint-initdb.d/06-campaign-finance.sql",
    "../domains/campaign_finance/schema/nc_orchestrator_tables.sql:/docker-entrypoint-initdb.d/07-nc-orchestrator.sql",
    "../domains/campaign_finance/schema/dark_money_tables.sql:/docker-entrypoint-initdb.d/08-dark-money.sql",
    "../domains/property/schema/tables.sql:/docker-entrypoint-initdb.d/09-property.sql",
    "../domains/civics/schema/tables.sql:/docker-entrypoint-initdb.d/10-civics.sql",
    "../infra/db/09-age-graph-bootstrap.sql:/docker-entrypoint-initdb.d/11-age-graph-bootstrap.sql",
]
_EXPECTED_CADDY_PUBLIC_PORTS = {"80:80", "443:443"}

# Representative env vars for compose config validation.
# These satisfy all required interpolations (e.g. ${POSTGRES_PASSWORD:?...}).
_COMPOSE_CONFIG_ENV = {
    "POSTGRES_PASSWORD": "test-compose-config-pw",
    "ORIGIN": "https://test.civibus.example.com",
    "PUBLIC_HOSTNAME": "test.civibus.example.com",
    "CIVIBUS_API_KEYS": "test-key-1",
    "CIVIBUS_ADMIN_API_KEYS": "test-admin-key-1",
    "CIVIBUS_RATE_LIMIT_REQUESTS": "321",
    "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS": "654",
    "CIVIBUS_API_KEY": "test-web-key",
    # Bind mount path is now a required env var on the prod compose so a
    # typoed env file fails the stack at start. Test fixture provides any
    # path; tests that exercise the missing-env-var failure parametrise
    # over this var explicitly.
    "CIVIBUS_DB_DATA_PATH": "/tmp/civibus-test-pgdata",
}
_L13_SECRET_FIXTURE_VALUES = {
    "PRODUCTION_ENV_FILE": "POSTGRES_PASSWORD=stage1-db-secret\nCIVIBUS_API_KEYS=stage1-api-secrets\n",
    "POSTGRES_PASSWORD": "stage1-db-password",
    "CIVIBUS_API_KEYS": "stage1-api-keys",
    "CIVIBUS_ADMIN_API_KEYS": "stage1-admin-keys",
    "CIVIBUS_API_KEY": "stage1-web-key",
}


def _port_mapping_binds_all_interfaces(port_mapping: str | dict) -> bool:
    """Return True when a compose port mapping would publish on all host interfaces."""
    if isinstance(port_mapping, dict):
        host_ip = port_mapping.get("host_ip")
        if host_ip == "0.0.0.0":
            return True
        if host_ip:
            return False

        published_port = port_mapping.get("published")
        if published_port is None:
            return False

        # Keep the existing Stage 2 allowance for variable-interpolated host ports.
        return "$" not in str(published_port)

    mapping_text = str(port_mapping)
    mapping_parts = mapping_text.split(":")

    if len(mapping_parts) >= 3:
        return mapping_parts[0] == "0.0.0.0"

    if len(mapping_parts) == 2:
        host_port = mapping_parts[0]
        # Keep the existing Stage 2 allowance for variable-interpolated host ports.
        return "$" not in host_port

    # A single published port also uses Docker's default all-interface bind.
    return True


def _port_mapping_host_to_target(port_mapping: str | dict) -> str | None:
    """Return the normalized host:target mapping for compose port definitions."""
    if isinstance(port_mapping, dict):
        published_port = port_mapping.get("published")
        target_port = port_mapping.get("target")
        if published_port is None or target_port is None:
            return None
        return f"{published_port}:{target_port}"

    mapping_parts = str(port_mapping).split(":")
    if len(mapping_parts) < 2:
        return None

    return f"{mapping_parts[-2]}:{mapping_parts[-1]}"


def _run_compose_config(
    *,
    env_updates: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose config` with representative env vars for this stack."""
    env = {
        **_COMPOSE_CONFIG_ENV,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    for env_var_name, env_var_value in (env_updates or {}).items():
        if env_var_value is None:
            env.pop(env_var_name, None)
        else:
            env[env_var_name] = env_var_value

    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _read_required_text(path: Path, missing_message: str) -> str:
    assert path.exists(), missing_message
    return path.read_text(encoding="utf-8")


def _docker_compose_available() -> bool:
    """Return True when the docker CLI and compose subcommand are both usable."""
    if shutil.which("docker") is None:
        return False

    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


_has_docker_compose = _docker_compose_available()


@pytest.fixture(scope="module")
def compose_config() -> dict:
    """Parse the production compose file via PyYAML for structural assertions."""
    assert COMPOSE_FILE.exists(), f"Missing {COMPOSE_FILE}"
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


def test_compose_file_exists():
    assert COMPOSE_FILE.exists(), f"Expected {COMPOSE_FILE} to exist"


def test_api_dockerfile_exports_uv_environment_python_on_path():
    """Ad-hoc python invocations must resolve deps without making the active venv writable at runtime."""
    dockerfile_text = _read_required_text(
        API_DOCKERFILE_FILE,
        f"Expected API image Dockerfile {API_DOCKERFILE_FILE} to exist",
    )
    assert 'ENV PATH="/app/.venv/bin:$PATH"' in dockerfile_text, (
        "infra/api/Dockerfile must export /app/.venv/bin on PATH so ad-hoc python commands "
        "inside infra-api-1 resolve runtime dependencies like PyYAML"
    )
    assert "chown -R civibus:civibus /app" not in dockerfile_text, (
        "infra/api/Dockerfile must keep /app owned by root so the runtime user cannot mutate "
        "the virtualenv or source tree that are active on PATH"
    )


def test_declares_exactly_four_services(compose_config: dict):
    services = set(compose_config.get("services", {}).keys())
    assert services == {"db", "api", "web", "caddy"}, f"Expected {{db, api, web, caddy}}, got {services}"


def test_api_and_web_have_ghcr_image_fields(compose_config: dict):
    """api and web must share the CIVIBUS_IMAGE_REPO contract with IMAGE_TAG override support."""
    image_repo_expr = "${CIVIBUS_IMAGE_REPO:-ghcr.io/gridl-dev/civibus_dev}"
    services = compose_config["services"]
    for service_name in ("api", "web"):
        image_value = services[service_name].get("image")
        assert image_value, f"{service_name} service must declare an image field"
        assert image_repo_expr in image_value, (
            f"{service_name} image must include image repo expression {image_repo_expr!r}, got {image_value!r}"
        )
        expected_image = f"{image_repo_expr}/{service_name}:${{IMAGE_TAG:-latest}}"
        assert image_value == expected_image, (
            f"{service_name} image must use the CIVIBUS_IMAGE_REPO source of truth while allowing IMAGE_TAG override; "
            f"expected {expected_image!r}, got {image_value!r}"
        )


def test_api_service_uses_federal_first_content_floor_defaults(compose_config: dict):
    api_environment = compose_config["services"]["api"]["environment"]

    expected_floors = {
        f"CIVIBUS_HEALTH_CONTENT_FLOOR_{check_name.upper()}": (
            f"${{CIVIBUS_HEALTH_CONTENT_FLOOR_{check_name.upper()}:-{floor}}}"
        )
        for check_name, floor in FEDERAL_FIRST_CONTENT_FLOORS.items()
    }

    assert {key: api_environment[key] for key in expected_floors} == expected_floors


def test_only_caddy_may_bind_to_all_interfaces(compose_config: dict):
    """Only ingress caddy may publish host ports on all interfaces."""
    services = compose_config["services"]
    for service_name, service_config in services.items():
        for port_mapping in service_config.get("ports", []):
            binds_all_interfaces = _port_mapping_binds_all_interfaces(port_mapping)
            if service_name == "caddy":
                assert binds_all_interfaces, f"caddy ingress must bind publicly reachable host ports: {port_mapping!r}"
                continue

            assert not binds_all_interfaces, f"{service_name} must not bind to all interfaces: {port_mapping!r}"


def test_db_exposes_localhost_only_port(compose_config: dict):
    db_ports = compose_config["services"]["db"].get("ports")
    assert db_ports == ["127.0.0.1:5432:5432"], (
        "db service must expose exactly localhost-only 5432 mapping for host-side ingest commands"
    )


def test_web_has_no_direct_host_port_mapping(compose_config: dict):
    """web must not publish host ports once Caddy is the only public ingress."""
    web_service = compose_config["services"]["web"]
    assert web_service.get("ports") is None, (
        "web service must not publish host ports; caddy is the only public ingress listener"
    )


def test_caddy_exposes_exact_public_ingress_ports(compose_config: dict):
    """caddy must publish both required ingress host ports for public HTTPS traffic."""
    caddy_ports = compose_config["services"]["caddy"].get("ports", [])
    assert caddy_ports, "caddy service must publish ingress port mappings"

    normalized_caddy_ports = []
    for port_mapping in caddy_ports:
        normalized_mapping = _port_mapping_host_to_target(port_mapping)
        assert normalized_mapping is not None, (
            f"caddy ingress mappings must declare both published and target ports: {port_mapping!r}"
        )
        normalized_caddy_ports.append(normalized_mapping)

    assert set(normalized_caddy_ports) == _EXPECTED_CADDY_PUBLIC_PORTS, (
        "caddy must publish exactly 80:80 and 443:443 host-to-container mappings"
    )
    assert len(normalized_caddy_ports) == len(_EXPECTED_CADDY_PUBLIC_PORTS), (
        "caddy must not publish additional host ingress ports beyond 80 and 443"
    )


def test_db_bootstrap_includes_domain_schemas_and_age_graph(compose_config: dict):
    """First-run init must load core/domain schemas and one-time AGE graph bootstrap."""
    db_volumes = compose_config["services"]["db"].get("volumes", [])
    mounted_init_entries = [entry for entry in db_volumes if isinstance(entry, str) and "initdb.d" in entry]
    assert mounted_init_entries == _EXPECTED_DB_INIT_MOUNTS, (
        "db init mounts must deterministically load core SQL, campaign_finance/property "
        "domain schemas, and one-time AGE graph bootstrap artifact"
    )


def test_age_bootstrap_sql_is_idempotent_and_self_bootstrapping():
    """AGE bootstrap SQL must be safe on first deploy and graph creation retry."""
    assert AGE_BOOTSTRAP_SQL_FILE.exists(), f"Expected {AGE_BOOTSTRAP_SQL_FILE} to exist"
    sql_text = AGE_BOOTSTRAP_SQL_FILE.read_text().lower()

    assert "create extension if not exists age" in sql_text, (
        "AGE bootstrap SQL must ensure extension installation in the same init artifact"
    )
    assert "if not exists (select 1 from ag_catalog.ag_graph where name = 'civibus')" in sql_text, (
        "AGE bootstrap SQL must guard civibus graph creation with NOT EXISTS"
    )
    assert "perform ag_catalog.create_graph('civibus')" in sql_text, (
        "AGE bootstrap SQL must create the civibus graph when missing"
    )


@pytest.mark.parametrize(
    ("port_mapping", "expected_all_interface_bind"),
    [
        ("127.0.0.1:5432:5432", False),
        ("0.0.0.0:5432:5432", True),
        ("5432:5432", True),
        ("80:80", True),
        ("443:443", True),
        ({"host_ip": "127.0.0.1", "published": "5432", "target": 5432}, False),
        ({"published": "5432", "target": 5432}, True),
        ({"published": "80", "target": 80}, True),
    ],
)
def test_port_binding_policy_flags_implicit_all_interface_binds(
    port_mapping: str | dict,
    expected_all_interface_bind: bool,
):
    """Guard the helper logic behind the Stage 2 host-port policy."""
    assert _port_mapping_binds_all_interfaces(port_mapping) is expected_all_interface_bind


def test_api_depends_on_db_healthy(compose_config: dict):
    api_deps = compose_config["services"]["api"].get("depends_on", {})
    assert "db" in api_deps, "api must depend on db"
    assert api_deps["db"].get("condition") == "service_healthy", "api must wait for db to be healthy"


def test_web_depends_on_api_healthy(compose_config: dict):
    web_deps = compose_config["services"]["web"].get("depends_on", {})
    assert "api" in web_deps, "web must depend on api"
    assert web_deps["api"].get("condition") == "service_healthy", "web must wait for api to be healthy"


def test_db_has_healthcheck(compose_config: dict):
    db_svc = compose_config["services"]["db"]
    assert "healthcheck" in db_svc, "db service must have a healthcheck"


def test_api_has_healthcheck(compose_config: dict):
    api_svc = compose_config["services"]["api"]
    assert "healthcheck" in api_svc, "api service must have a healthcheck"


def test_all_services_on_civibus_network(compose_config: dict):
    """All services must be attached to the civibus bridge network."""
    networks = compose_config.get("networks", {})
    assert "civibus" in networks, "Must define a 'civibus' network"
    assert set(compose_config["services"].keys()) == {"db", "api", "web", "caddy"}

    for name, svc in compose_config["services"].items():
        svc_networks = svc.get("networks", [])
        assert "civibus" in svc_networks, f"{name} must be on civibus network"


def test_api_environment_has_production_settings(compose_config: dict):
    """API service must set CIVIBUS_ENV=production and correct DB connection vars."""
    api_env = compose_config["services"]["api"].get("environment", {})
    assert api_env.get("CIVIBUS_ENV") == "production"
    assert api_env.get("POSTGRES_HOST") == "db"
    # POSTGRES_PORT should be 5432 (int or string) for container networking
    port_val = api_env.get("POSTGRES_PORT")
    assert str(port_val) == "5432", f"Expected POSTGRES_PORT=5432, got {port_val}"


def test_web_environment_has_api_base_url(compose_config: dict):
    web_env = compose_config["services"]["web"].get("environment", {})
    assert web_env.get("CIVIBUS_API_BASE_URL") == "http://api:8000"
    assert web_env.get("NODE_ENV") == "production"


def test_env_production_example_exists():
    env_example = REPO_ROOT / ".env.production.example"
    assert env_example.exists(), f"Expected {env_example} to exist"


def test_env_production_example_documents_required_vars():
    """The env example must mention all deployment-controlled variables."""
    env_example = REPO_ROOT / ".env.production.example"
    content = env_example.read_text()

    required_vars = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "CIVIBUS_API_KEYS",
        "CIVIBUS_ADMIN_API_KEYS",
        "CIVIBUS_RATE_LIMIT_REQUESTS",
        "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS",
        "ORIGIN",
        "CIVIBUS_API_KEY",
    ]
    for var in required_vars:
        assert var in content, f".env.production.example must document {var}"


def test_env_production_example_documents_explicit_env_file_usage():
    """Docs must use --env-file so root `.env` works with infra compose path."""
    env_example = REPO_ROOT / ".env.production.example"
    content = env_example.read_text()
    expected_command = "docker compose --env-file .env -f infra/docker-compose.prod.yml up"
    assert expected_command in content, (
        ".env.production.example must document compose usage with explicit --env-file .env "
        "when using -f infra/docker-compose.prod.yml"
    )


def test_caddy_reads_caddyfile_via_bind_mount(compose_config: dict):
    caddy_volumes = compose_config["services"]["caddy"].get("volumes", [])
    assert "../infra/Caddyfile:/etc/caddy/Caddyfile:ro" in caddy_volumes, (
        "caddy service must mount infra/Caddyfile read-only as /etc/caddy/Caddyfile"
    )


def test_caddyfile_exists_for_ingress_configuration():
    assert CADDYFILE_FILE.exists(), f"Expected ingress config {CADDYFILE_FILE} to exist"


def test_caddyfile_uses_public_hostname_placeholder_and_www_redirect():
    caddyfile_text = _read_required_text(
        CADDYFILE_FILE,
        f"Expected ingress config {CADDYFILE_FILE} to exist",
    )
    assert "{$PUBLIC_HOSTNAME}" in caddyfile_text, (
        "Caddyfile must use {$PUBLIC_HOSTNAME} placeholder for runtime-derived hostname"
    )
    assert "www.{$PUBLIC_HOSTNAME}" in caddyfile_text, "Caddyfile must define an explicit www hostname block"
    assert "https://{$PUBLIC_HOSTNAME}{uri}" in caddyfile_text, (
        "Caddyfile must redirect www host to https://{$PUBLIC_HOSTNAME}{uri}"
    )
    assert "permanent" in caddyfile_text, "www redirect must be permanent"


def test_caddyfile_uses_production_acme_not_staging():
    """Caddyfile must never use the Let's Encrypt staging ACME endpoint."""
    caddyfile_text = _read_required_text(
        CADDYFILE_FILE,
        f"Expected ingress config {CADDYFILE_FILE} to exist",
    )
    assert "acme-staging-v02" not in caddyfile_text, (
        "Caddyfile must use production Let's Encrypt ACME (the Caddy default), "
        "not the staging endpoint acme-staging-v02.api.letsencrypt.org"
    )
    explicit_acme_ca_values = re.findall(r"^\s*acme_ca\s+(\S+)", caddyfile_text, re.MULTILINE)
    for explicit_acme_ca_value in explicit_acme_ca_values:
        assert explicit_acme_ca_value == "https://acme-v02.api.letsencrypt.org/directory", (
            "If acme_ca is explicitly set, every explicit value must point to the production Let's Encrypt endpoint"
        )


def test_caddyfile_routes_api_prefix_to_api_service():
    """Canonical ingress must expose API routes through /api/* on the same HTTPS host."""
    caddyfile_text = _read_required_text(
        CADDYFILE_FILE,
        f"Expected ingress config {CADDYFILE_FILE} to exist",
    )
    ingress_routes_snippet = re.search(
        r"^\(civibus_ingress_routes\)\s*\{(?P<body>.*?)^\}$",
        caddyfile_text,
        re.MULTILINE | re.DOTALL,
    )
    assert ingress_routes_snippet is not None, (
        "Caddyfile must define a shared civibus_ingress_routes snippet for every served hostname"
    )

    api_route_block = re.search(
        r"handle_path\s+/api/\*\s*\{(?P<body>.*?)\}",
        ingress_routes_snippet.group("body"),
        re.DOTALL,
    )
    assert api_route_block is not None, "Caddyfile must route /api/* requests to the backend API service"
    assert re.search(r"^\s*reverse_proxy\s+\{\$CIVIBUS_API_UPSTREAM:api:8000\}\s*$", caddyfile_text, re.MULTILINE), (
        "Caddyfile must proxy /api/* traffic to the CIVIBUS_API_UPSTREAM placeholder "
        "with api:8000 as the compose default"
    )
    assert re.search(
        r"^\{\$CIVIBUS_SITE_SCHEME\}\{\$PUBLIC_HOSTNAME\}\s*\{\s*import\s+civibus_ingress_routes\s*\}",
        caddyfile_text,
        re.MULTILINE,
    ), "Caddyfile must serve the canonical PUBLIC_HOSTNAME with shared ingress routes"


def test_caddyfile_serves_fly_compatibility_hostname_without_acme():
    caddyfile_text = _read_required_text(
        CADDYFILE_FILE,
        f"Expected ingress config {CADDYFILE_FILE} to exist",
    )
    assert "http://{$CIVIBUS_FLY_COMPAT_HOSTNAME:127.0.0.1}" in caddyfile_text, (
        "Fly compatibility hostname must use explicit http:// because Fly terminates TLS at the edge"
    )
    assert re.search(
        r"^http://\{\$CIVIBUS_FLY_COMPAT_HOSTNAME:127\.0\.0\.1\}\s*\{\s*import\s+civibus_ingress_routes\s*\}",
        caddyfile_text,
        re.MULTILINE,
    ), "Caddyfile must serve the Fly compatibility hostname with shared ingress routes"


def test_fastapi_routes_match_caddy_stripped_api_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    caddyfile_text = _read_required_text(
        CADDYFILE_FILE,
        f"Expected ingress config {CADDYFILE_FILE} to exist",
    )
    assert re.search(r"handle_path\s+/api/\*", caddyfile_text), (
        "Caddyfile must keep using handle_path /api/* for this route mapping contract"
    )

    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "compose-route-test-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "5")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "10")
    sys.modules.pop("api.main", None)
    api_main = importlib.import_module("api.main")
    app = api_main.create_app()

    get_route_paths = {
        route.path
        for route in app.routes
        if route.path.startswith("/") and route.methods and "GET" in route.methods and route.path.startswith("/api/")
    }
    unmirrored_paths = {
        route_path: route_path.removeprefix("/api")
        for route_path in get_route_paths
        if route_path.removeprefix("/api") not in {route.path for route in app.routes}
    }

    assert not unmirrored_paths, (
        "FastAPI routes registered under /api/... must also be reachable at the "
        f"Caddy post-strip path; missing mirrors: {unmirrored_paths}"
    )


def test_prod_compose_wrapper_reuses_env_lib_contract():
    wrapper_text = _read_required_text(
        PROD_COMPOSE_WRAPPER_FILE,
        f"Expected rollout wrapper {PROD_COMPOSE_WRAPPER_FILE} to exist",
    )
    assert "set -euo pipefail" in wrapper_text
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in wrapper_text
    assert 'repo_root="$(cd "${script_dir}/../.." && pwd)"' in wrapper_text
    assert 'source "${script_dir}/env_lib.sh"' in wrapper_text
    assert "load_civibus_env" in wrapper_text
    assert "load_env_assignments() {" not in wrapper_text
    assert 'cd "${repo_root}"' in wrapper_text


def test_prod_compose_wrapper_uses_single_self_contained_prod_file():
    """The Apr 30 incident was caused by `docker compose up` loading the
    dev compose because the prod stack required two `-f` flags. The new
    contract: prod compose is one self-contained file. The wrapper must
    NOT chain in any overlay (volume-override, dev, etc.)."""
    wrapper_text = _read_required_text(
        PROD_COMPOSE_WRAPPER_FILE,
        f"Expected rollout wrapper {PROD_COMPOSE_WRAPPER_FILE} to exist",
    )
    assert "--env-file .env" in wrapper_text, "wrapper must pass --env-file .env to docker compose"
    assert "-f infra/docker-compose.prod.yml" in wrapper_text, (
        "wrapper must include the primary production compose file"
    )
    # Apr 30 regression guard: no overlay files. Specifically reject the
    # old volume-override, but also catch any future overlay creep.
    assert "volume-override" not in wrapper_text, (
        "wrapper must NOT chain volume-override.yml — bind mount is now in prod.yml"
    )
    assert wrapper_text.count("-f ") == 1, (
        "wrapper must reference exactly one compose file; multiple -f flags reintroduce "
        "the overlay foot-gun that caused the Apr 30 incident"
    )
    assert '"$@"' in wrapper_text, "wrapper must forward caller-provided docker compose args to preserve rollout flags"


def test_prod_compose_file_bind_mounts_db_data_with_required_env_var():
    """The bind mount path must come from a REQUIRED env var (?Set …) so
    a missing/typoed env file fails the stack at start time instead of
    silently provisioning an empty named volume — the literal Apr 30
    failure mode."""
    prod_compose_text = _read_required_text(
        COMPOSE_FILE,
        f"Expected prod compose {COMPOSE_FILE} to exist",
    )
    # Required-env-var bind mount: `${CIVIBUS_DB_DATA_PATH:?...}:/var/lib/postgresql/data`.
    assert "CIVIBUS_DB_DATA_PATH:?" in prod_compose_text, (
        "prod compose must require CIVIBUS_DB_DATA_PATH; a missing var must fail at start"
    )
    assert ":/var/lib/postgresql/data" in prod_compose_text, (
        "prod compose must mount the data path to PostgreSQL's data directory"
    )
    # No anonymous named volume for the DB — a fresh volume is the bug.
    assert "civibus_db_data:" not in prod_compose_text, (
        "prod compose must NOT declare a named volume for the DB data dir; use a required-env-var bind mount instead"
    )


def test_prod_compose_wrapper_derives_public_hostname_before_compose():
    wrapper_text = _read_required_text(
        PROD_COMPOSE_WRAPPER_FILE,
        f"Expected rollout wrapper {PROD_COMPOSE_WRAPPER_FILE} to exist",
    )
    assert 'origin_without_scheme="${ORIGIN#*://}"' in wrapper_text, (
        "wrapper must strip URL scheme from ORIGIN before hostname derivation"
    )
    assert 'origin_authority="${origin_without_scheme%%/*}"' in wrapper_text, (
        "wrapper must isolate ORIGIN authority before PUBLIC_HOSTNAME export"
    )
    assert re.search(r'export PUBLIC_HOSTNAME="\$\{origin_authority%%:\*\}"', wrapper_text), (
        "wrapper must export PUBLIC_HOSTNAME as the ORIGIN authority host portion"
    )
    assert "docker compose" in wrapper_text, "wrapper must execute docker compose commands"

    export_index = wrapper_text.index("export PUBLIC_HOSTNAME")
    compose_index = wrapper_text.index("docker compose")
    assert export_index < compose_index, "wrapper must export PUBLIC_HOSTNAME before first docker compose invocation"


def _load_deploy_workflow() -> tuple[str, dict]:
    """Return the raw workflow text plus parsed YAML for deploy contract assertions."""
    assert DEPLOY_WORKFLOW_FILE.exists(), f"Expected {DEPLOY_WORKFLOW_FILE} to exist"
    workflow_text = DEPLOY_WORKFLOW_FILE.read_text()
    return workflow_text, yaml.safe_load(workflow_text)


def _workflow_triggers(workflow_config: dict) -> dict:
    """Return the 'on' block, handling PyYAML's bare ``on:`` → True key coercion."""
    return workflow_config.get("on", workflow_config.get(True, {}))


def _deploy_run_scripts(workflow_config: dict) -> list[str]:
    deploy_steps = workflow_config["jobs"]["deploy"].get("steps", [])
    return [step.get("run", "") for step in deploy_steps if isinstance(step, dict) and "run" in step]


def _sample_l13_live_snapshot() -> dict[str, object]:
    """Build a deterministic live snapshot fixture with secret-bearing values."""
    return {
        "workflow": {
            "deploy_if": "github.repository == 'gridl-hq/civibus'",
            "deploy_env": {
                "FLY_API_TOKEN": _L13_SECRET_FIXTURE_VALUES["PRODUCTION_ENV_FILE"],
                "PROD_SMOKE_BASE_URL": "${{ vars.PROD_SMOKE_BASE_URL }}",
            },
            "fly_deploy_commands": [
                "flyctl deploy -c infra/fly/api.fly.toml --remote-only",
                "flyctl deploy web -c infra/fly/web.fly.toml --remote-only",
                "flyctl deploy -c infra/fly/caddy.fly.toml --remote-only",
            ],
        },
        "fly_apps": {
            "api": "civibus-api",
            "web": "civibus-web",
            "caddy": "civibus-caddy",
        },
    }


def test_deploy_workflow_replaces_ssh_compose_rollout_with_fly_deploys():
    workflow_text, workflow_config = _load_deploy_workflow()
    deploy_scripts = _deploy_run_scripts(workflow_config)

    assert "Deploy placeholder" not in workflow_text, (
        "deploy workflow must remove placeholder message and run the real rollout"
    )
    expected_deploy_commands = [
        "flyctl deploy -c infra/fly/api.fly.toml --remote-only",
        "flyctl deploy web -c infra/fly/web.fly.toml --remote-only",
        "flyctl deploy -c infra/fly/caddy.fly.toml --remote-only",
    ]
    assert sum("flyctl deploy" in script for script in deploy_scripts) == 3
    for expected_command in expected_deploy_commands:
        assert workflow_text.count(expected_command) == 1
    command_order_indexes = [workflow_text.index(command) for command in expected_deploy_commands]
    assert command_order_indexes == sorted(command_order_indexes)

    for obsolete_fragment in ("prod_compose.sh", "bootstrap_prod_vm.sh", "docker pull ghcr.io/", "ssh "):
        assert obsolete_fragment not in workflow_text


def test_deploy_workflow_excludes_db_refresh_and_local_bootstrap_concerns() -> None:
    workflow_text, _ = _load_deploy_workflow()

    forbidden_fragments = (
        "infra/fly/db.fly.toml",
        "infra/fly/refresh.fly.toml",
        "civibus-db",
        "civibus-refresh",
        "domains/civics/schema/migrations/2026_04_27_electoral_division_geometry.sql",
        "make db-up",
        "make refresh",
    )
    for forbidden_fragment in forbidden_fragments:
        assert forbidden_fragment not in workflow_text


def test_l13_contract_owners_align_with_deploy_and_compose_helpers() -> None:
    """Reuse existing workflow helper seams while pinning Fly L13 owner files."""
    _, workflow_config = _load_deploy_workflow()
    assert len(_deploy_run_scripts(workflow_config)) >= 4

    expected_owner_files = {
        ".github/workflows/deploy.yml",
        "infra/fly/api.fly.toml",
        "infra/fly/web.fly.toml",
        "infra/fly/caddy.fly.toml",
    }
    assert set(keel_gate_l13.CONTRACT_OWNER_FILES.values()) == expected_owner_files


def test_l13_diff_output_redacts_secret_values_and_keeps_non_secret_comparison(tmp_path: Path) -> None:
    repo_contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)
    live_snapshot = _sample_l13_live_snapshot()
    live_snapshot["fly_apps"]["api"] = "civibus-api-hotfix"  # type: ignore[index]

    result = keel_gate_l13.evaluate_contract_drift(
        repo_contract=repo_contract,
        normalized_live_snapshot=keel_gate_l13.normalize_live_snapshot(live_snapshot),
        deploy_id="test-redaction",
        debt_entries=[],
        produced_at=keel_gate_l13._utc_now(),
    )
    evidence_path = keel_gate_l13.write_l13_evidence(
        evaluation=result,
        deploy_id="test-redaction",
        repo_sha="abc12345",
        produced_at=keel_gate_l13._utc_now(),
        evidence_root=tmp_path,
    )

    serialized_diff = json.dumps(result.diff_entries, sort_keys=True)
    evidence_text = evidence_path.read_text(encoding="utf-8")

    for secret_value in _L13_SECRET_FIXTURE_VALUES.values():
        assert secret_value not in serialized_diff
        assert secret_value not in evidence_text

    assert any(entry["path"] == "fly_apps.api" for entry in result.diff_entries)
    assert "fly_apps.api" in evidence_text


def test_deploy_workflow_uses_fly_secret_and_public_smoke_variable():
    workflow_text, _ = _load_deploy_workflow()
    env_example = REPO_ROOT / ".env.production.example"
    env_example_text = env_example.read_text()

    assert "secrets.FLY_API_TOKEN" in workflow_text
    assert "vars.PROD_SMOKE_BASE_URL" in workflow_text
    for secret_name in (
        "HETZNER_HOST",
        "HETZNER_SSH_KEY",
        "HETZNER_KNOWN_HOSTS",
        "PRODUCTION_ENV_FILE",
    ):
        assert secret_name not in env_example_text, (
            f".env.production.example must not include CI-only deploy secret {secret_name}"
        )


def test_deploy_workflow_has_guarded_fly_production_job():
    workflow_text, workflow_config = _load_deploy_workflow()
    deploy_env = workflow_config["jobs"]["deploy"].get("env", {})

    assert workflow_config["jobs"].keys() == {"deploy"}
    assert workflow_config["jobs"]["deploy"]["if"] == "github.repository == 'gridl-hq/civibus'"
    assert workflow_config["jobs"]["deploy"]["environment"] == "production"
    assert deploy_env.get("FLY_API_TOKEN") == "${{ secrets.FLY_API_TOKEN }}"
    assert deploy_env.get("PROD_SMOKE_BASE_URL") == "${{ vars.PROD_SMOKE_BASE_URL }}"
    assert "superfly/flyctl-actions/setup-flyctl" in workflow_text


def test_deploy_workflow_has_workflow_dispatch_trigger():
    """Deploy workflow must support manual triggering via workflow_dispatch."""
    _, workflow_config = _load_deploy_workflow()
    triggers = _workflow_triggers(workflow_config)
    assert "workflow_dispatch" in triggers, (
        "deploy workflow must include workflow_dispatch trigger for manual deploys via 'gh workflow run'"
    )
    assert "push" in triggers, "deploy workflow must retain push trigger alongside workflow_dispatch"


def test_deploy_workflow_runs_production_smoke_against_actions_variable():
    workflow_text, workflow_config = _load_deploy_workflow()
    deploy_steps = workflow_config["jobs"]["deploy"].get("steps", [])
    smoke_steps = [step for step in deploy_steps if step.get("name") == "Run production smoke gate"]
    assert len(smoke_steps) == 1
    smoke_step = smoke_steps[0]
    smoke_run = smoke_step["run"]

    assert smoke_step["working-directory"] == "web"
    assert 'if [[ -z "${PROD_SMOKE_BASE_URL}" ]]' in smoke_run
    assert "SMOKE_MODE=production" in smoke_run
    assert 'SMOKE_BASE_URL="${PROD_SMOKE_BASE_URL}"' in smoke_run
    assert "tests/smoke/production_deploy.spec.ts" in smoke_run
    assert workflow_text.index("flyctl deploy -c infra/fly/caddy.fly.toml --remote-only") < workflow_text.index(
        "Run production smoke gate"
    )


# ---------------------------------------------------------------------------
# docker compose config integration tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_docker_compose, reason="docker not on PATH")
class TestComposeConfig:
    """Run `docker compose config` to catch interpolation and parser regressions."""

    @pytest.fixture(scope="class")
    def resolved_config(self) -> dict:
        """Invoke `docker compose config` and return the parsed YAML output."""
        result = _run_compose_config()
        assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"
        return json.loads(result.stdout)

    def test_compose_config_resolves_without_errors(self, resolved_config: dict):
        assert "services" in resolved_config

    def test_resolved_api_env_interpolation(self, resolved_config: dict):
        """Verify compose interpolated env vars into the api service."""
        api_env = resolved_config["services"]["api"]["environment"]
        assert api_env["CIVIBUS_ENV"] == "production"
        assert api_env["POSTGRES_HOST"] == "db"
        assert api_env["POSTGRES_PORT"] == "5432"
        assert api_env["POSTGRES_PASSWORD"] == "test-compose-config-pw"
        assert api_env["CIVIBUS_CORS_ORIGIN"] == "https://test.civibus.example.com"
        assert api_env["CIVIBUS_API_KEYS"] == "test-key-1"
        assert api_env["CIVIBUS_ADMIN_API_KEYS"] == "test-admin-key-1"
        assert api_env["CIVIBUS_RATE_LIMIT_REQUESTS"] == "321"
        assert api_env["CIVIBUS_RATE_LIMIT_WINDOW_SECONDS"] == "654"

    def test_resolved_web_env_interpolation(self, resolved_config: dict):
        """Verify compose interpolated env vars into the web service."""
        web_env = resolved_config["services"]["web"]["environment"]
        assert web_env["CIVIBUS_API_BASE_URL"] == "http://api:8000"
        assert web_env["NODE_ENV"] == "production"
        assert web_env["ORIGIN"] == "https://test.civibus.example.com"
        assert web_env["PUBLIC_ORIGIN"] == "https://test.civibus.example.com"
        assert web_env["CIVIBUS_API_KEY"] == "test-web-key"

    def test_resolved_caddy_env_interpolation(self, resolved_config: dict):
        caddy_service = resolved_config["services"]["caddy"]
        caddy_env = caddy_service["environment"]
        assert caddy_env["PUBLIC_HOSTNAME"] == "test.civibus.example.com"

    def test_resolved_public_ingress_has_no_web_port_mapping(self, resolved_config: dict):
        """Only caddy may publish public host ports in resolved compose config."""
        web_service = resolved_config["services"]["web"]
        assert web_service.get("ports") is None, (
            "resolved web service must not publish host ports when Caddy is ingress"
        )

        caddy_ports = resolved_config["services"]["caddy"].get("ports", [])
        normalized_caddy_ports = []
        for port_mapping in caddy_ports:
            normalized_mapping = _port_mapping_host_to_target(port_mapping)
            assert normalized_mapping is not None, (
                f"resolved caddy ingress mappings must include both published and target ports: {port_mapping!r}"
            )
            normalized_caddy_ports.append(normalized_mapping)

        assert set(normalized_caddy_ports) == _EXPECTED_CADDY_PUBLIC_PORTS, (
            "resolved caddy service must publish exactly 80:80 and 443:443"
        )
        assert len(normalized_caddy_ports) == len(_EXPECTED_CADDY_PUBLIC_PORTS), (
            "resolved caddy service must not publish ingress ports beyond 80 and 443"
        )

    def test_resolved_api_healthcheck_uses_python(self, resolved_config: dict):
        """Healthcheck must use python3 (not curl) — regression guard."""
        api_hc = resolved_config["services"]["api"]["healthcheck"]["test"]
        # CMD-SHELL format: ["CMD-SHELL", "command string"]
        cmd = api_hc[-1] if isinstance(api_hc, list) else api_hc
        assert "python3" in cmd, f"API healthcheck must use python3, got: {cmd}"
        assert "curl" not in cmd, f"API healthcheck must not use curl, got: {cmd}"

    @pytest.mark.parametrize(
        "missing_env_var_name",
        [
            "POSTGRES_PASSWORD",
            "ORIGIN",
            "CIVIBUS_API_KEYS",
            "CIVIBUS_ADMIN_API_KEYS",
            "CIVIBUS_API_KEY",
            # Apr 30 regression guard: missing bind-mount path must fail
            # compose at config time, not silently bootstrap an empty
            # named volume. This is the load-bearing assertion.
            "CIVIBUS_DB_DATA_PATH",
        ],
    )
    def test_compose_config_requires_critical_env_vars(self, missing_env_var_name: str):
        """Missing production env vars must fail at compose-config time, not runtime."""
        result = _run_compose_config(env_updates={missing_env_var_name: None})
        output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0, (
            f"docker compose config must fail when {missing_env_var_name} is missing; output was:\n{output}"
        )
        assert missing_env_var_name in output, (
            f"docker compose config error output must mention {missing_env_var_name}; output was:\n{output}"
        )


def test_bootstrap_script_skips_base_package_install_when_prereqs_already_present() -> None:
    """Repeated deploy runs must avoid unnecessary apt lock contention on already-provisioned hosts."""
    script_text = _read_required_text(
        BOOTSTRAP_SCRIPT_FILE,
        f"Expected bootstrap script {BOOTSTRAP_SCRIPT_FILE} to exist",
    )
    assert "if command -v curl >/dev/null 2>&1" in script_text
    assert "&& command -v git >/dev/null 2>&1" in script_text
    assert "&& command -v gpg >/dev/null 2>&1" in script_text
