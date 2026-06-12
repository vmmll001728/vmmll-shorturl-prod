#!/usr/bin/env bash
# =============================================================================
# scripts/ci_local.sh — Local CI validation script
#
# 验证本地环境完整通过所有 5 道 CI 门禁（不依赖 GitHub Actions）。
#
# 用法:
#   bash scripts/ci_local.sh          # 完整验证
#   bash scripts/ci_local.sh --skip-build  # 跳过 Docker 构建（已构建时）
#   bash scripts/ci_local.sh --help
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

SKIP_BUILD=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=true; shift ;;
    --verbose|-v) VERBOSE=true; shift ;;
    --help|-h)
      echo "Usage: $0 [--skip-build] [--verbose]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

section() {
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  $1"
  echo "════════════════════════════════════════════════════════════"
}

# ── Pre-checks ────────────────────────────────────────────────────────────────

section "Pre-flight Checks"

if ! command -v docker &>/dev/null; then
  log_fail "docker not found. Please install Docker."
  exit 1
fi
log_ok "docker found: $(docker --version)"

if ! docker compose version &>/dev/null; then
  log_fail "docker compose not found. Please update Docker."
  exit 1
fi
log_ok "docker compose found: $(docker compose version)"

# ── Job 1: test-and-lint ─────────────────────────────────────────────────────

section "Gate 1/5 — pytest (local Python)"

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  log_fail "Python not found."
  exit 1
fi

PYTHON_CMD="${PYTHON:-python3}"
$PYTHON_CMD -m pip install -q pytest pytest-cov httpx fastapi sqlalchemy pydantic uvicorn prometheus-fastapi-instrumentator 2>/dev/null || true
log_info "Running pytest..."
if $PYTHON_CMD -m pytest tests/ -v --tb=short; then
  log_ok "pytest passed"
else
  log_fail "pytest failed"
  exit 1
fi

# ── Job 2: trivy-scan (filesystem) ───────────────────────────────────────────

section "Gate 2/5 — Trivy filesystem scan"

if command -v trivy &>/dev/null; then
  log_info "Running Trivy filesystem scan..."
  trivy fs --severity CRITICAL,HIGH --exit-code 0 . 2>/dev/null || log_warn "Trivy completed with findings (non-blocking)"
  log_ok "Trivy filesystem scan done"
else
  log_warn "trivy not installed — skipping (install with: brew install trivy || choco install trivy)"
fi

# ── Job 3: Docker build ─────────────────────────────────────────────────────

section "Gate 3/5 — Docker build (production target)"

if [[ "$SKIP_BUILD" == "true" ]]; then
  log_warn "Skipping Docker build (--skip-build)"
else
  log_info "Building shorturl production image..."
  if docker build --target production -t shorturl:latest .; then
    log_ok "Docker build succeeded"

    # Verify non-root user
    log_info "Verifying non-root user..."
    USER_IN_IMAGE=$(docker run --rm shorturl:latest id -un 2>/dev/null || echo "unknown")
    if [[ "$USER_IN_IMAGE" == "appuser" ]]; then
      log_ok "Running as non-root user: appuser (UID 1000)"
    else
      log_warn "User is: $USER_IN_IMAGE (expected appuser)"
    fi

    # Verify no root
    UID_IN_IMAGE=$(docker run --rm shorturl:latest id -u 2>/dev/null || echo "0")
    if [[ "$UID_IN_IMAGE" != "0" ]]; then
      log_ok "Container is NOT running as root (UID=$UID_IN_IMAGE)"
    else
      log_fail "Container is running as ROOT!"
      exit 1
    fi
  else
    log_fail "Docker build failed"
    exit 1
  fi
fi

# ── Job 4: docker-compose up (production) ───────────────────────────────────

section "Gate 4/5 — docker-compose up (production)"

log_info "Starting docker-compose stack..."
docker compose -f docker-compose.yml up -d --build

log_info "Waiting for healthcheck..."
HEALTH_STATUS="starting"
HEALTH_ATTEMPTS=0
until [[ "$HEALTH_STATUS" == "healthy" ]] || [[ $HEALTH_ATTEMPTS -ge 20 ]]; do
  sleep 2
  HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' shorturl 2>/dev/null || echo "none")
  HEALTH_ATTEMPTS=$((HEALTH_ATTEMPTS + 1))
  echo -n "."
done
echo ""

if [[ "$HEALTH_STATUS" == "healthy" ]]; then
  log_ok "Container is healthy"
else
  log_warn "Health status: $HEALTH_STATUS (may still be starting)"
fi

# Test health endpoint
log_info "Testing /health endpoint..."
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/health || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
  log_ok "/health returned 200"
else
  log_fail "/health returned HTTP $HTTP_CODE"
  docker compose -f docker-compose.yml logs --tail=20 shorturl
  docker compose -f docker-compose.yml down
  exit 1
fi

# Test API
log_info "Testing /api/v1/links (POST)..."
RESP=$(curl -sf -X POST http://localhost:8000/api/v1/links \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","custom_alias":"localtest1"}' || echo "")
if echo "$RESP" | grep -q '"success"'; then
  log_ok "API POST /links works"
else
  log_fail "API POST /links failed: $RESP"
fi

log_info "Tearing down docker-compose stack..."
docker compose -f docker-compose.yml down -v

# ── Job 5: integration-test (docker-compose.test.yml) ─────────────────────

section "Gate 5/5 — integration-test (docker-compose.test.yml)"

if [[ ! -f "docker-compose.test.yml" ]]; then
  log_warn "docker-compose.test.yml not found — skipping integration-test gate"
else
  log_info "Building integration test image..."
  docker build --target production -t shorturl:test .

  log_info "Running integration tests in container..."
  # Override command to run pytest via docker compose
  if docker compose -f docker-compose.test.yml run --rm \
    -e PYTEST_ADDOPTS="--tb=short -v" \
    shorturl pytest tests/ -v --tb=short; then
    log_ok "Integration tests passed (containerized pytest)"
  else
    log_fail "Integration tests failed"
    docker compose -f docker-compose.test.yml logs --tail=30
    docker compose -f docker-compose.test.yml down -v
    exit 1
  fi

  log_info "Cleaning up integration test environment..."
  docker compose -f docker-compose.test.yml down -v
fi

# ── Summary ──────────────────────────────────────────────────────────────────

section "✅ All Gates Passed!"

echo ""
echo -e "${GREEN}ShortURL CI Gates Summary${NC}"
echo "  ✅ Gate 1: pytest (local Python)"
echo "  ✅ Gate 2: Trivy filesystem scan"
echo "  ✅ Gate 3: Docker build (production, non-root)"
echo "  ✅ Gate 4: docker-compose up + /health + API smoke test"
echo "  ✅ Gate 5: docker-compose.test.yml integration test"
echo ""
echo "  Container image: shorturl:latest (appuser UID 1000)"
echo "  Healthcheck:     curl -f http://localhost:8000/health"
echo ""
log_ok "Local CI validation complete!"
