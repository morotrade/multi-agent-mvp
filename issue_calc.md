### Goal
Create a minimal Python package `src/calc` with basic arithmetic ops and a tiny CLI.

### Scope & Files
- Create:
  - `src/calc/__init__.py`
  - `src/calc/ops.py`  (functions: add(a,b), sub(a,b), mul(a,b), div(a,b) with ZeroDivisionError)
  - `src/calc/__main__.py` (CLI: `python -m calc 2 + 3` prints `5`)
  - `tests/test_ops.py` (unit tests covering normal cases and division by zero)
- Update:
  - `README.md` with a short “Install & Usage” section describing the CLI and Python usage.

### Requirements
- Python 3.11+, type hints + docstrings.
- Clean, minimal, focused change set. **Do not edit** `.github/**`.
- Keep code simple and readable; no external deps.
- Include tests that show expected behavior and edge cases (0, negatives, ZeroDivisionError).
- CLI must support: `+`, `-`, `x` (or `*`), `/`. Print result and exit code 0; on invalid input, non-zero exit and helpful message.

### Acceptance Criteria
- Running `python -m calc 7 / 2` prints `3.5`.
- Running `python -m calc 4 / 0` exits non-zero and prints an error.
- `tests/test_ops.py` passes locally (conceptually; CI not required).
- README shows how to run CLI and import `calc.ops`.

### Reviewer Policy
essential-only (BLOCKERs must be fixed before merge; IMPORTANT/SUGGESTION optional)

### IMPORTANT for the LLM
- Output must be a single **unified diff** fenced in ```diff including `--- a/...` and `+++ b/...` headers.
- Modify only the files listed above.
- Do not touch `.github` or workflow files.
