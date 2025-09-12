# Pre-Flight Checklist for User Testing

## ✅ Repository Secrets (Required)

### LLM API Keys (At least ONE required)
- [ ] `OPENAI_API_KEY` - For GPT models
- [ ] `ANTHROPIC_API_KEY` - For Claude models  
- [ ] `GEMINI_API_KEY` - For Gemini models

### GitHub Tokens
- [ ] `GITHUB_TOKEN` - Automatically provided (default permissions OK)
- [ ] `GH_CLASSIC_TOKEN` - **Required for Project v2 integration**
  - Must be Personal Access Token with `project` scope
  - If not provided, Project status updates will be skipped (non-blocking)

## ✅ Repository Variables (Optional)

### Model Selection
- [ ] `ANALYZER_MODEL` (default: gpt-4o-mini)
- [ ] `REVIEWER_MODEL` (default: gpt-4o-mini)  
- [ ] `DEVELOPER_MODEL` (default: gpt-4o-mini)

### Project v2 Configuration (Optional - for status tracking)
- [ ] `GITHUB_PROJECT_ID` or `GH_PROJECT_ID` - Your Project v2 ID
- [ ] `PROJECT_STATUS_FIELD_ID` - Status field ID in Project
- [ ] `PROJECT_STATUS_BACKLOG_ID` - "Backlog" option ID
- [ ] `PROJECT_STATUS_INPROGRESS_ID` - "In Progress" option ID  
- [ ] `PROJECT_STATUS_INREVIEW_ID` - "In Review" option ID
- [ ] `PROJECT_STATUS_DONE_ID` - "Done" option ID

## ✅ Workflow Files

### Required Triggers
- [ ] **analyzer.yml**: `issues: [opened, labeled]`
- [ ] **reviewer.yml**: `pull_request: [opened, synchronize, reopened, labeled]`
- [ ] **dev.yml**: 
  - Issue mode: `issues: [labeled]` with condition `contains(github.event.label.name, 'bot:implement')`
  - PR-fix mode: `pull_request: [labeled, synchronize]` with condition for `need-fix` label
- [ ] **progress.yml**: `pull_request: [closed]`

### Critical Steps in dev.yml
- [ ] Git configuration step added (see workflow snippet)
- [ ] `PR_NUMBER: ${{ github.event.pull_request.number }}` in PR-fix job
- [ ] All LLM API keys included in both jobs

## ✅ File Deployment

### Core Files (All required)
- [ ] `analyzer.py` - Clean deduplicated version
- [ ] `dev.py` - Complete with PR-fix mode
- [ ] `reviewer.py` - With both Project ID aliases
- [ ] `progress.py` - Enhanced version only
- [ ] `utils.py` - **Single consolidated version** (remove any duplicates)

## ✅ Smoke Test Sequence (10 minutes)

### Test 1: Issue → Development
1. [ ] Create an issue with clear requirements
2. [ ] Add `bot:implement` label
3. [ ] Verify: Analyzer creates tasks, auto-starts first one
4. [ ] Verify: Dev creates branch + PR for first task

### Test 2: PR → Review Loop  
1. [ ] On created PR, verify Reviewer creates sticky comment
2. [ ] Verify: `need-fix` or `ready-to-merge` label applied
3. [ ] If `need-fix`: push empty commit or re-apply label
4. [ ] Verify: Dev applies fixes to same branch

### Test 3: Progress Management
1. [ ] When PR is ready, merge it
2. [ ] Verify: Progress manager starts next task
3. [ ] Verify: Project status updates (if configured)

## ⚠️ Known Limitations (Non-blocking)

- **Diff application failures**: When modifying existing files fails, Dev will report clearly but won't auto-retry with full file strategy (requires manual intervention)
- **Project integration**: Requires GH_CLASSIC_TOKEN with project scope, otherwise gracefully skips
- **LLM failures**: All agents degrade gracefully with clear error messages

## 🚀 Ready to Test

Once all checkboxes above are complete, you're ready for user testing. The system provides:
- Complete reviewer ↔ developer loop on same PR/branch
- Automatic task progression 
- Robust error handling and fallbacks
- Clear user feedback at each step

Start with a simple issue to test the full workflow end-to-end.