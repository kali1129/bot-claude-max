# Quality Assessment

## Purpose

This scorecard evaluates supervised DEMO quality for the XM MT5 bot without making any profitability claim.

It measures:

- Telegram control quality
- runtime stability
- safety and gating quality
- analysis and fallback quality
- execution-path quality
- operator visibility
- supervised DEMO trading behavior

It does not measure:

- profitability
- expectancy
- strategy edge

## Commands

PowerShell:

```powershell
.\scripts\run_quality_assessment.ps1 -Mode live
```

Python:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_quality_assessment.py --mode live
```

JSON output:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_quality_assessment.py --mode live --json
```

## Outputs

The assessment prints:

- category score from `0.0` to `10.0`
- strengths
- weaknesses
- blockers
- recommended next actions
- overall rating
- unattended readiness

It also writes artifacts to:

- `logs/<mode>/quality_assessments/quality_assessment_<timestamp>.json`
- `logs/<mode>/quality_assessments/quality_assessment_<timestamp>.txt`

## Ratings

Overall rating:

- `NOT READY`
- `SUPERVISED DEMO READY`
- `DEMO STRONG`

Separate unattended readiness:

- `NOT READY FOR UNATTENDED`
- `SUPERVISED DEMO READY`

## Evidence sources

The scorecard reuses live repo evidence instead of subjective impressions:

- `run_self_check.py`
- `validate_demo_operation.py`
- control-center normalized views
- Telegram menu wiring
- Task Scheduler autostart state
- live runtime process state
- latest bridge/runtime artifacts

## Interpretation

- High score means the bot is operationally well-controlled for supervised DEMO use.
- High score does not imply profitable trading.
- Reduced-risk posture can still score well if it is coherent, symbol-aware, and not falsely hard-blocking.
