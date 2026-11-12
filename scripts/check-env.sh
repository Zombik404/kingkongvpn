#!/usr/bin/env bash
# Report which development tools are available and which phases they unblock.
# Usage: scripts/check-env.sh
set -u

check() {  # name, phase-note, version-command...
  local name=$1 note=$2; shift 2
  if command -v "$name" >/dev/null 2>&1; then
    printf "  %-14s OK       %s\n" "$name" "$("$@" 2>&1 | head -1)"
  else
    printf "  %-14s MISSING  (needed for %s)\n" "$name" "$note"
  fi
}

echo "Core"
check git        "everything"            git --version
check python3    "backend, bot, agent"   python3 --version
check node       "web, admin"            node --version
check npm        "web, admin"            npm --version
check docker     "dev stack"             docker --version
if docker info >/dev/null 2>&1; then echo "  docker daemon  running"; else echo "  docker daemon  NOT running"; fi
check psql       "Phase 2 tests"         psql --version
check redis-server "Phase 2 tests"       redis-server --version
echo "VPN / infra"
check wg         "Phase 3 integration"   wg --version
check nft        "Phase 3 firewall"      nft --version
check ip         "Phase 3 netns tests"   ip -V
check ansible    "Phase 3 provisioning"  ansible --version
check terraform  "Phase 3/4 automation"  terraform version
echo "Clients"
check flutter    "Phase 6/7"             flutter --version
check dart       "Phase 6/7"             dart --version
check xcodebuild "iOS/macOS builds"      xcodebuild -version
echo "Python packages"
python3 - <<'PY'
import importlib
mods = ["fastapi", "sqlalchemy", "alembic", "asyncpg", "redis", "celery", "argon2",
        "jwt", "cryptography", "pydantic", "pydantic_settings", "httpx", "pytest",
        "pytest_asyncio", "aiogram"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        print(f"  {m:18} OK       {getattr(mod, '__version__', '')}")
    except Exception:
        print(f"  {m:18} MISSING")
PY
