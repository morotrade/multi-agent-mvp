# -*- coding: utf-8 -*-
import os, re
from typing import Tuple, List

_HEADER_RE = re.compile(r"(?m)^(--- .+)\n(\+\+\+ .+)\n")

def _parse_header_pair(h1: str, h2: str) -> Tuple[str, str, str, str]:
    def split_hdr(h: str) -> Tuple[str, str]:
        rest = h[4:].strip()  # drop '--- ' or '+++ '
        if rest.startswith('a/'): return ('a', rest[2:])
        if rest.startswith('b/'): return ('b', rest[2:])
        if rest == '/dev/null' or rest.startswith('/dev/null'): return ('/dev/null', '')
        return ('?', rest)
    s1, p1 = split_hdr(h1)
    s2, p2 = split_hdr(h2)
    return s1, p1, s2, p2

def normalize_diff_headers_against_fs(diff: str, project_root: str) -> str:
    """
    Corregge le coppie header (---/+++) in base all'esistenza dei file:
    - se il file di destinazione (b/path) NON esiste => forza '--- /dev/null' (nuovo file)
    - se '--- /dev/null' ma il file esiste => forza '--- a/<path>' (modifica)
    """
    if not diff or '--- ' not in diff or '+++ ' not in diff:
        return diff

    parts: List[str] = []
    last_end = 0
    for m in _HEADER_RE.finditer(diff):
        parts.append(diff[last_end:m.start()])
        h1, h2 = m.group(1), m.group(2)
        s1, p1, s2, p2 = _parse_header_pair(h1, h2)

        dest_path = p2 if s2 == 'b' else ''
        dest_exists = os.path.exists(dest_path) if dest_path else False

        new_h1, new_h2 = h1, h2
        # Nuovo file: destinazione non esiste -> sorgente deve essere /dev/null
        if dest_path and not dest_exists:
            if not h1.strip().endswith('/dev/null'):
                new_h1 = '--- /dev/null'
        # Caso inverso raro: sorgente /dev/null ma file già esiste -> è una modifica
        if h1.strip().endswith('/dev/null') and dest_exists and dest_path:
            new_h1 = f'--- a/{dest_path}'

        parts.append(new_h1 + "\n" + new_h2 + "\n")
        last_end = m.end()

    parts.append(diff[last_end:])
    return "".join(parts)

def coerce_unified_diff(diff: str) -> str:
    """
    Best-effort coercion per unified diff generati dal modello:
    - normalizza CRLF→LF
    - garantisce newline finale
    - dentro gli hunk (@@ ... @@) prefissa con ' ' le righe senza '+', '-', ' ', '\\'
    """
    if not isinstance(diff, str) or not diff:
        return diff
    s = diff.replace("\r\n", "\n")
    lines = s.split("\n")
    out: list[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@ "):
            in_hunk = True
            out.append(line)
            continue
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
            in_hunk = False
            out.append(line)
            continue
        if in_hunk:
            if line and not (line.startswith("+") or line.startswith("-") or line.startswith(" ") or line.startswith("\\")):
                out.append(" " + line)
            else:
                out.append(line)
        else:
            out.append(line)
    coerced = "\n".join(out)
    if not coerced.endswith("\n"):
        coerced += "\n"
    return coerced