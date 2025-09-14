from utils.file_validation import validate_diff_files
from dev_core.path_isolation import enforce_diff_under_root

def enforce_all(diff: str, project_root: str, *, allow_project_readme: bool = True) -> None:
    """Guardia unica: whitelist/denylist + radice progetto."""
    # 1) validazioni base (sicurezza + allow/deny); ora puoi fargli passare la root
    validate_diff_files(diff, project_root=project_root, allow_project_readme=allow_project_readme)
    # 2) cintura+bretelle: tutto sotto root
    enforce_diff_under_root(diff, project_root)