# SPDX-License-Identifier: MIT
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass(frozen=True)
class PromptProfile:
    name: str
    max_full_lines: int = 350   # file <= 350 linee → includi full
    add_context_lines: int = 30 # per snippet (non implementato qui, hook pronto)

class PromptBuilder:
    """
    Costruisce prompt robusti per Dev/Fix: sezioni chiare, scope vincolato,
    format diff rigido. Profilo SAFE/FAST selezionabile.
    """
    def __init__(self, profile: PromptProfile | None = None):
        self.profile = profile or PromptProfile(name="SAFE")

    def build_devfix_prompt(
        self,
        base_sha: str,
        branch: str,
        findings_text: str,
        scope_must_edit: List[str],
        scope_must_not_edit: Optional[List[str]],
        file_snapshots: Dict[str, Dict],  # path -> {"lines": int, "content": str}
        one_line_summary: str = "",
        project_structure: Optional[List[str]] = None,
    ) -> str:
        scope_must_not_edit = scope_must_not_edit or []
        files_blocks: List[str] = []
        for path, meta in file_snapshots.items():
            content = meta["content"]
            files_blocks.append(f"[{path}]\n{content}")

        scope_block = "\n".join(f"- {p}" for p in scope_must_edit)
        mne_block = "\n".join(f"- {p}" for p in scope_must_not_edit)

        proj_struct_block = ""
        if project_structure:
            # elenco compatto, solo path, niente contenuti
            proj_struct_block = "# PROJECT STRUCTURE (paths)\n" + "\n".join(f"- {p}" for p in project_structure[:500])

        files_section = "\n\n".join(files_blocks)
        prompt = f"""SYSTEM: Senior Python Developer. Output ONLY a valid unified diff. No explanations.
        
# CONTEXT
PR: (thread) | base_sha: {base_sha} | branch: {branch}
Summary: {one_line_summary}

# REPO INVARIANTS
- Line endings: LF
- Path prefix: a/ b/
- Edit ONLY files listed in #SCOPE. Do NOT touch any other file.

# SCOPE
MUST-EDIT:
{scope_block}
MUST-NOT-EDIT:
{mne_block if mne_block else "(none)"}

# REVIEWER FINDINGS
{findings_text.strip()}

# REQUIREMENTS
- Fix ONLY the issues described in the findings.
- Keep Python 3.11+ compatibility.
- Update/add minimal tests if logic changes.
- Do NOT rename public functions/classes unless strictly required.
- Maintain imports order and lint-friendly formatting.

# ACCEPTANCE TESTS
- pytest -q must pass.
- flake8/mypy on edited files must be clean.

# DIFF FORMAT
- Start with: diff --git a/<path> b/<path>
- Use headers: --- a/<path> and +++ b/<path>
- Use hunks: @@ -l,c +l,c @@
- No text outside the diff. No code fences. No markdown.

# FILE SNAPSHOTS
{files_section}

{proj_struct_block if project_structure else ""}

# OUTPUT
Emit ONLY the full unified diff.
"""
        return prompt
