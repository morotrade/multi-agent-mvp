# -*- coding: utf-8 -*-
"""
Diff extraction and application utilities
"""
import os
import re
import subprocess
import shutil
from typing import List
from .file_validation import is_path_safe

def extract_single_diff(markdown_text: str) -> str:
    """
    Estrae un unified diff dal testo. Se l'LLM produce più blocchi ```diff/```patch,
    li combina in un unico diff valido (concatenazione), ripulendo eventuali header
    "diff --git" e ritagliando dal primo '--- ' di ciascun blocco.
    """
    if not markdown_text or not markdown_text.strip():
        raise Exception("Empty response from LLM")
    
    # Try to find diff blocks
    patterns = [
        r"```(?:diff|patch)\s*([\s\S]*?)```",  # Explicit diff/patch blocks
        r"```\s*(---[\s\S]*?\+\+\+[\s\S]*?)```",  # Generic blocks with diff headers
        r"```\s*([\s\S]*?)```"  # Any code blocks
    ]
    
    blocks = []
    for pattern in patterns:
        blocks = re.findall(pattern, markdown_text, re.MULTILINE)
        if blocks:
            break
    
    # Se troviamo più blocchi, combiniamoli in un unico diff valido
    if not blocks:
        raise Exception("No diff block found in LLM output")

    parts = []
    for b in blocks:
        b = (b or "").strip()
        if not b:
            continue
        # Se il blocco inizia con 'diff --git', ritaglia fino al primo header unificato
        if b.startswith("diff --git"):
            m = re.search(r"(?m)^--- (?:a/|/dev/null)", b)
            if m:
                b = b[m.start():]
        # Considera solo blocchi che hanno almeno l'header unificato
        if not re.search(r"(?m)^--- (?:a/|/dev/null)", b):
            continue
        parts.append(b)

    if not parts:
        raise Exception("Invalid diff format: cannot extract a valid unified diff block")

    diff = "\n".join(parts).strip()
    if not diff:
        raise Exception("Diff block is empty")

    # Normalize line endings and encoding
    lines = diff.split("\n")
    cleaned_lines = []
    for line in lines:
        # Remove non-ASCII characters that could cause issues
        cleaned_line = line.encode("ascii", "ignore").decode("ascii")
        cleaned_lines.append(cleaned_line)
    diff = "\n".join(cleaned_lines)

    # Enhanced validation (vale anche per diff combinati)
    if not re.search(r"^--- (?:a/|/dev/null)", diff, flags=re.M):
        raise Exception("Invalid diff format: must start with '--- a/' or '--- /dev/null'")
    
    if not re.search(r"^\+\+\+ (?:b/|/dev/null)", diff, flags=re.M):
        raise Exception("Invalid diff format: must contain '+++ b/' (or '+++ /dev/null') headers")
    
    if not re.search(r"^@@.*@@", diff, flags=re.M):
        raise Exception("Invalid diff format: must contain at least one hunk header '@@'")
    
    # Size check
    if len(diff) > 800_000:
        raise Exception("Diff too large (>800KB)")
    
    # Check for multiple file headers (limite di sicurezza; multi-file ok entro 20)
    file_count = len(re.findall(r"^--- (?:a/|/dev/null)", diff, flags=re.M))
    if file_count > 20:
        raise Exception(f"Diff touches too many files ({file_count}). "
                       "Break into smaller changes.")

    return diff

def apply_diff_resilient(diff_content: str) -> bool:
    """Apply diff with multiple strategies and explicit failure modes"""
    if not diff_content or not diff_content.strip():
        print("❌ No diff content to apply")
        return False
    
    # Normalize diff
    normalized = diff_content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"

    # Check if this diff contains in-place modifications
    has_modifications = bool(re.search(r"^--- a/", normalized, flags=re.M))
    has_new_files = bool(re.search(r"^--- /dev/null", normalized, flags=re.M))
    
    print(f"📋 Diff analysis: modifications={has_modifications}, new_files={has_new_files}")

    path = "/tmp/patch.diff"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(normalized)

        # Strategy 1: git apply with check
        try:
            print("🔧 Strategy 1: git apply --check + apply...")
            result = subprocess.run(
                ["git", "apply", "--check", "--whitespace=fix", path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                subprocess.run(["git", "apply", "--whitespace=fix", path], 
                             check=True, timeout=120)
                print("✅ Git apply successful")
                return True
            else:
                print(f"⚠️ Git apply check failed: {result.stderr[:200]}")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            print(f"⚠️ Git apply failed: {str(e)[:200]}")

        # Strategy 2: git apply --3way (better for conflicts)
        try:
            print("🔧 Strategy 2: git apply --3way...")
            subprocess.run(["git", "apply", "--3way", "--whitespace=fix", path], 
                         check=True, timeout=180)
            print("✅ Git apply --3way successful")
            return True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            print(f"⚠️ Git apply --3way failed: {str(e)[:200]}")

        # Strategy 3: patch command
        if shutil.which("patch"):
            try:
                print("🔧 Strategy 3: patch command...")
                subprocess.run(["patch", "-p1", "-i", path], 
                             check=True, timeout=180)
                print("✅ Patch command successful")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"⚠️ Patch command failed: {str(e)[:200]}")

        # Strategy 4: Manual creation (ONLY for new files)
        if has_modifications and not has_new_files:
            print("❌ Cannot apply in-place modifications manually")
            print("   LLM should regenerate with full file content for existing files")
            return False
        elif has_new_files:
            try:
                print("🔧 Strategy 4: manual file creation...")
                return apply_diff_manually(normalized)
            except Exception as e:
                print(f"⚠️ Manual application failed: {e}")

        print("❌ All diff application strategies failed")
        return False

    finally:
        try:
            os.remove(path)
        except OSError:
            pass

def apply_diff_manually(diff_content: str) -> bool:
    """
    Manual application for NEW FILES ONLY (--- /dev/null ... +++ b/FILE)
    Does NOT handle in-place modifications to existing files
    """
    created_any = False
    
    # Split by new file markers
    files = re.split(r"(?m)^--- /dev/null\s*\n\+\+\+ b/", diff_content)
    
    # The first split chunk is preamble; subsequent chunks start with file path
    for chunk in files[1:]:
        # Extract file path (first line until newline)
        first_newline = chunk.find("\n")
        if first_newline == -1:
            continue
            
        rel_path = chunk[:first_newline].strip()
        file_chunk = chunk[first_newline+1:]
        
        if not rel_path:
            continue

        # Collect added lines from hunks
        added_lines = []
        in_hunk = False
        
        for line in file_chunk.splitlines():
            if line.startswith("@@") and "@@" in line[2:]:
                in_hunk = True
                continue
            
            if in_hunk:
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])
                elif line.startswith("\\"):
                    # Handle "\ No newline at end of file"
                    continue
        
        # Write file if we have content
        if added_lines:
            if not is_path_safe(rel_path):
                print(f"❌ Unsafe path in diff: {rel_path}")
                return False
            try:
                # Create directory if needed
                dir_path = os.path.dirname(rel_path)
                if dir_path:
                    os.makedirs(dir_path, exist_ok=True)
                
                # Write file
                with open(rel_path, "w", encoding="utf-8", newline="\n") as f:
                    content = "\n".join(added_lines)
                    if not content.endswith("\n"):
                        content += "\n"
                    f.write(content)
                
                print(f"✅ Created file: {rel_path}")
                created_any = True
                
            except Exception as e:
                print(f"❌ Failed to create {rel_path}: {e}")
                return False
    
    return created_any
