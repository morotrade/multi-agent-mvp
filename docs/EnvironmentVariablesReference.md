# Environment Variables Reference

Use this unified set of environment variables across all workflows (analyzer.yml, reviewer.yml, dev.yml, progress.yml):

```yaml
env:
  # Core GitHub
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  GH_CLASSIC_TOKEN: ${{ secrets.GH_CLASSIC_TOKEN }}  # Required for Project v2
  GITHUB_REPOSITORY: ${{ github.repository }}
  
  # Project v2 Integration (both aliases supported)
  GITHUB_PROJECT_ID: ${{ vars.GITHUB_PROJECT_ID }}
  GH_PROJECT_ID: ${{ vars.GH_PROJECT_ID }}  # Alternative alias
  PROJECT_STATUS_FIELD_ID: ${{ vars.PROJECT_STATUS_FIELD_ID }}
  PROJECT_STATUS_BACKLOG_ID: ${{ vars.PROJECT_STATUS_BACKLOG_ID }}
  PROJECT_STATUS_INPROGRESS_ID: ${{ vars.PROJECT_STATUS_INPROGRESS_ID }}
  PROJECT_STATUS_INREVIEW_ID: ${{ vars.PROJECT_STATUS_INREVIEW_ID }}
  PROJECT_STATUS_DONE_ID: ${{ vars.PROJECT_STATUS_DONE_ID }}
  
  # LLM API Keys (at least one required)
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  
  # Model Selection (optional)
  ANALYZER_MODEL: ${{ vars.ANALYZER_MODEL || 'gpt-4o-mini' }}
  REVIEWER_MODEL: ${{ vars.REVIEWER_MODEL || 'gpt-4o-mini' }}
  DEVELOPER_MODEL: ${{ vars.DEVELOPER_MODEL || 'gpt-4o-mini' }}
```

## Critical Notes:

1. **GH_CLASSIC_TOKEN**: Required for Project v2 operations. Must have `project` scope.
2. **Both Project ID aliases**: All files now support both `GITHUB_PROJECT_ID` and `GH_PROJECT_ID` 
3. **Git configuration**: For dev.yml PR-fix mode, ensure git is configured:
   ```yaml
   - name: Configure git
     run: |
       git config --global user.name "AI Developer"
       git config --global user.email "ai-dev@users.noreply.github.com"
   ```