# ========= CONFIG =========
# Anteprima (true) oppure ESECUZIONE (false)
$DRY_RUN = $false
# Se vuoi farlo correre sul repo corrente in automatico:
$REPO = gh repo view --json nameWithOwner --jq .nameWithOwner 2>$null
if (-not $REPO) {
  Write-Host "Impossibile determinare il repo corrente. Imposta manualmente es: 'owner/name'." -ForegroundColor Yellow
  # $REPO = "morotrade/multi-agent-mvp"
  exit 1
}
Write-Host "Repository: $REPO" -ForegroundColor Cyan
# ==========================

# --- 1) CHIUDI PR aperte generate dal bot (o con branch 'bot/...') ---
Write-Host "`n[PR] Ricerca PR aperte del bot..." -ForegroundColor Magenta
$prs = gh pr list --repo $REPO --state open --limit 200 --json number,title,headRefName,author `
  --jq ".[] | select(.author.login==\""github-actions[bot]\"" or (.title|startswith(\""[Bot] \"")) or (.headRefName|startswith(\""bot/\""))) | [.number, .headRefName, .title] | @tsv"

if (-not $prs) {
  Write-Host "Nessuna PR da chiudere." -ForegroundColor DarkGray
} else {
  $prs -split "`n" | ForEach-Object {
    if (-not $_) { return }
    $parts = $_ -split "`t"
    $num   = $parts[0]
    $head  = $parts[1]
    $title = $parts[2]
    Write-Host "PR #$num  ($head)  — $title"
    if (-not $DRY_RUN) {
      # chiude la PR e prova a cancellare il branch remoto
      gh pr close $num --repo $REPO --delete-branch 2>$null
    }
  }
}

# --- 2) CHIUDI ISSUE aperte generate dal bot (o con label bot:*) ---
Write-Host "`n[ISSUE] Ricerca issue aperte del bot..." -ForegroundColor Magenta
$issues = gh issue list --repo $REPO --state open --limit 300 --json number,title,author,labels `
  --jq ".[] | select(.author.login==\""github-actions[bot]\"" or ( [.labels[].name][] | startswith(\""bot:\"")) or (.title|startswith(\""[Sprint] \""))) | [.number, .title] | @tsv"

if (-not $issues) {
  Write-Host "Nessuna issue da chiudere." -ForegroundColor DarkGray
} else {
  $issues -split "`n" | ForEach-Object {
    if (-not $_) { return }
    $parts = $_ -split "`t"
    $num   = $parts[0]
    $title = $parts[1]
    Write-Host "Issue #$num — $title"
    if (-not $DRY_RUN) {
      gh issue close $num --repo $REPO 2>$null
    }
  }
}

# --- 3) ELIMINA BRANCH REMOTI 'bot/*' rimasti orfani ---
Write-Host "`n[BRANCH REMOTI] Eliminazione 'bot/*'..." -ForegroundColor Magenta
git fetch origin --prune | Out-Null
$remoteBranches = git branch -r | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^origin\/bot\/' }
if (-not $remoteBranches) {
  Write-Host "Nessun branch remoto 'bot/*' da eliminare." -ForegroundColor DarkGray
} else {
  foreach ($rb in $remoteBranches) {
    $name = $rb -replace '^origin/',''
    Write-Host "Elimino remoto: $name"
    if (-not $DRY_RUN) {
      git push origin --delete $name 2>$null | Out-Null
    }
  }
}

# --- 4) ELIMINA BRANCH LOCALI 'bot/*' ---
Write-Host "`n[BRANCH LOCALI] Eliminazione 'bot/*'..." -ForegroundColor Magenta
$localBranches = git branch --format="%(refname:short)" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^bot\/' }
if (-not $localBranches) {
  Write-Host "Nessun branch locale 'bot/*' da eliminare." -ForegroundColor DarkGray
} else {
  foreach ($lb in $localBranches) {
    Write-Host "Elimino locale: $lb"
    if (-not $DRY_RUN) {
      git branch -D $lb 2>$null | Out-Null
    }
  }
}

Write-Host "`nFATTO." -ForegroundColor Green
if ($DRY_RUN) {
  Write-Host "Modalità ANTEPRIMA: nessuna modifica è stata eseguita." -ForegroundColor Yellow
  Write-Host "Imposta `$DRY_RUN = `$false e rilancia per applicare." -ForegroundColor Yellow
}