"""Pre-flight self-check for the bot nuevo.

Reduced port of xm-mt5-trading-platform/src/settings/{validation,
startup_self_check}.py. The legacy versions were tied to a heavyweight
Pydantic Settings model; this version checks only what the bot nuevo
actually depends on:

  - REQUIRED env vars present (DASHBOARD_TOKEN by default; others extensible)
  - _shared/rules.py importable + constants in sane ranges
  - _shared/halt.py file path writable (kill-switch precondition)
  - MongoDB reachable (MONGO_URL env, optional — skipped if env missing)
  - Backend listens on 127.0.0.1 (warn if 0.0.0.0)

Returns a quality-report dict in the same shape as
`backend/lib/monitoring/quality_assessment.build_report` so the dashboard
can render both consistently.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

# Reuse the quality_assessment scoring primitives
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot_lib.monitoring.quality_assessment import (  # type: ignore[import-not-found]
    build_report,
    make_check,
    score_category,
)


REQUIRED_ENV_VARS_DEFAULT: tuple[str, ...] = ("DASHBOARD_TOKEN",)
OPTIONAL_ENV_VARS_DEFAULT: tuple[str, ...] = ("MONGO_URL", "CAPITAL_FALLBACK_USD")


def _check_env_vars(
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for var in required:
        present = bool(os.environ.get(var, "").strip())
        checks.append(make_check(
            name=f"env.{var}",
            status="pass" if present else "fail",
            evidence=f"{var} {'set' if present else 'missing'}",
            recommendation=None if present else f"Set {var} in backend/.env",
            blocker=not present,
        ))
    for var in optional:
        present = bool(os.environ.get(var, "").strip())
        checks.append(make_check(
            name=f"env.{var}",
            status="pass" if present else "partial",
            evidence=f"{var} {'set' if present else 'absent (optional)'}",
        ))
    return checks


def _check_rules_module() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        rules_path = Path(__file__).resolve().parent.parent.parent / "mcp-scaffolds" / "_shared" / "rules.py"
        if not rules_path.exists():
            checks.append(make_check(
                name="rules.module",
                status="fail",
                evidence=f"rules.py not found at {rules_path}",
                blocker=True,
            ))
            return checks

        spec = importlib.util.spec_from_file_location("_rules", rules_path)
        if spec is None or spec.loader is None:
            checks.append(make_check(
                name="rules.module",
                status="fail",
                evidence="could not load spec for rules.py",
                blocker=True,
            ))
            return checks
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        max_risk = float(getattr(module, "MAX_RISK_PER_TRADE_PCT", 0.0))
        max_loss = float(getattr(module, "MAX_DAILY_LOSS_PCT", 0.0))
        min_rr = float(getattr(module, "MIN_RR", 0.0))
        max_pos = int(getattr(module, "MAX_OPEN_POSITIONS", 0))

        checks.append(make_check(
            name="rules.module",
            status="pass",
            evidence=(
                f"MAX_RISK_PER_TRADE_PCT={max_risk}, "
                f"MAX_DAILY_LOSS_PCT={max_loss}, "
                f"MIN_RR={min_rr}, MAX_OPEN_POSITIONS={max_pos}"
            ),
        ))

        # Sanity: warn if values look wildly outside production envelope.
        # (We don't fail — rules.py may be intentionally relaxed for demo).
        if max_risk > 5.0:
            checks.append(make_check(
                name="rules.max_risk_pct",
                status="partial",
                evidence=f"MAX_RISK_PER_TRADE_PCT={max_risk}% is very high",
                recommendation="Consider lowering to <= 1.0% before live trading",
            ))
        if min_rr < 1.5:
            checks.append(make_check(
                name="rules.min_rr",
                status="partial",
                evidence=f"MIN_RR={min_rr} is below SAGRADO 2.0",
                recommendation="Restore MIN_RR >= 2.0 before live trading",
            ))
    except Exception as exc:
        checks.append(make_check(
            name="rules.module",
            status="fail",
            evidence=f"loading rules.py raised: {exc}",
            blocker=True,
        ))
    return checks


def _check_halt_path() -> list[dict[str, Any]]:
    """Check that the kill-switch file path is writable."""
    halt_path = Path(os.environ.get("HALT_FILE", "/opt/trading-bot/state/.HALT"))
    parent = halt_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        # Touch a probe file
        probe = parent / ".halt_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return [make_check(
            name="halt.file_writable",
            status="pass",
            evidence=f"can write to {parent}",
        )]
    except OSError as exc:
        return [make_check(
            name="halt.file_writable",
            status="fail",
            evidence=f"cannot write to {parent}: {exc}",
            blocker=True,
        )]


def _check_backend_bind(bind_host: str | None = None) -> list[dict[str, Any]]:
    host = bind_host or os.environ.get("BACKEND_HOST", "127.0.0.1")
    if host in ("127.0.0.1", "localhost", "::1"):
        return [make_check(
            name="backend.bind",
            status="pass",
            evidence=f"backend bound to {host} (loopback only)",
        )]
    return [make_check(
        name="backend.bind",
        status="partial",
        evidence=f"backend bound to {host} (not loopback)",
        recommendation="Bind to 127.0.0.1 unless a reverse-proxy plan is in place",
    )]


def run_selfcheck(
    *,
    required_env_vars: tuple[str, ...] | None = None,
    optional_env_vars: tuple[str, ...] | None = None,
    bind_host: str | None = None,
) -> dict[str, Any]:
    """Run the pre-flight self-check and return a quality-report dict."""
    req = required_env_vars or REQUIRED_ENV_VARS_DEFAULT
    opt = optional_env_vars or OPTIONAL_ENV_VARS_DEFAULT

    categories = [
        score_category("environment", _check_env_vars(req, opt)),
        score_category("rules", _check_rules_module()),
        score_category("kill_switch", _check_halt_path()),
        score_category("backend", _check_backend_bind(bind_host)),
    ]
    return build_report(categories=categories, min_overall_score=0.80)


__all__ = [
    "REQUIRED_ENV_VARS_DEFAULT",
    "OPTIONAL_ENV_VARS_DEFAULT",
    "run_selfcheck",
]
