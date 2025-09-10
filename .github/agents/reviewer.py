#!/usr/bin/env python3
import os
import httpx
from utils import get_github_headers, call_llm_api, get_preferred_model

REPO = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER = os.environ["PR_NUMBER"]

def get_pr_diff() -> str:
    """Recupera il diff della PR"""
    headers = get_github_headers()
    headers["Accept"] = "application/vnd.github.v3.diff"

    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"

    with httpx.Client(timeout=60) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    return response.text[:80000]

def post_comment(body: str) -> None:
    """Posta un commento sulla PR"""
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    data = {"body": body}

    with httpx.Client(timeout=30) as client:
        response = client.post(url, headers=get_github_headers(), json=data)
        response.raise_for_status()

def load_prompt(prompt_name: str) -> str:
    """Carica il prompt dal file"""
    prompt_path = f".github/prompts/{prompt_name}.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"# Prompt per {prompt_name}\nAnalizza il codice seguendo le best practices."

def main():
    try:
        print("🤖 Avvio AI Code Reviewer...")

        # Recupera il diff
        diff = get_pr_diff()
        if not diff or len(diff.strip()) < 100:
            print("Nessun diff significativo da analizzare")
            return

        # Carica il prompt
        prompt_template = load_prompt("reviewer")

        # Avvolgiamo il diff in un blocco ```diff per un parsing robusto
        prompt = (
            f"{prompt_template}\n\n"
            f"## DIFF DA ANALIZZARE:\n\n"
            f"```diff\n{diff}\n```\n\n"
            f"## ANALISI:"
        )

        # Chiama l'AI
        print("📊 Analisi del codice in corso...")
        model = get_preferred_model("reviewer")
        analysis = call_llm_api(prompt, model=model)

        # Formatta il commento
        comment = f"""## 🤖 AI Code Review

{analysis}

---
*Revisione automatica generata da GitHub Actions*"""

        # Posta il commento
        post_comment(comment)
        print("✅ Revisione completata e commento postato")

    except Exception as e:
        error_msg = f"❌ Errore durante la revisione: {str(e)}"
        print(error_msg)

        # Posta un commento di errore solo se non è un errore di timeout
        if "timeout" not in str(e).lower():
            try:
                post_comment(f"## ❌ Errore AI Reviewer\n\n{error_msg}")
            except:
                pass

if __name__ == "__main__":
    main()
