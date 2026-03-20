#!/bin/bash
# Script automatico per Git Bash nella cartella del progetto
cd "/c/Users/ukg15381/Saved Games/multi_agent_mvp_main"

# Carica la SSH key
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_morotrade

# Mostra lo stato e i comandi disponibili
echo "========================================"
echo "Git Bash - Multi Agent MVP"
echo "========================================"
echo "Repository: morotrade/multi-agent-mvp"
echo ""
git status
echo ""
echo "Comandi disponibili:"
echo "  git add ."
echo "  git commit -m 'messaggio'"
echo "  git push"
echo "  git pull"
echo ""
