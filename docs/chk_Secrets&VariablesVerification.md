# Secrets & Variables Pre-Flight Check

## 2. GitHub Secrets Verification
Navigate to: **Settings → Secrets and variables → Actions**

### Required Secrets
```bash
# Check these are present (values hidden):
□ GITHUB_TOKEN (auto-provided by GitHub)
□ GH_CLASSIC_TOKEN (Personal Access Token)

# At least ONE LLM provider:
□ OPENAI_API_KEY
□ ANTHROPIC_API_KEY  
□ GEMINI_API_KEY
```

**Commands to verify secrets exist:**
```bash
# List repository secrets (won't show values)
gh api repos/:owner/:repo/actions/secrets | jq '.secrets[].name'

# Expected output should include:
# - GH_CLASSIC_TOKEN
# - One or more of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY
```

### GH_CLASSIC_TOKEN Scope Verification
**CRITICAL: Your Personal Access Token must have these scopes:**

```bash
# Test your GH_CLASSIC_TOKEN scopes:
curl -H "Authorization: token $GH_CLASSIC_TOKEN" \
  https://api.github.com/user | jq '.login'
# Should return your username

# Test Project v2 access specifically:
curl -H "Authorization: token $GH_CLASSIC_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -X POST \
  -d '{"query":"query{viewer{login}}"}' \
  https://api.github.com/graphql
# Should return your login without errors

# Test project scope (most critical):
curl -H "Authorization: token $GH_CLASSIC_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -X POST \
  -d '{"query":"query{viewer{projectsV2(first:1){nodes{id}}}}"}' \
  https://api.github.com/graphql
# Should NOT return scope errors
```

**Required PAT Scopes:**
- `repo` (full repository access)
- `workflow` (update workflow files)
- `project` (access Project v2 - CRITICAL)
- `read:org` (read organization data)

## 3. Repository Variables (Optional)
Navigate to: **Settings → Secrets and variables → Actions → Variables tab**

```bash
# Optional model configuration:
□ DEVELOPER_MODEL (e.g., "gpt-4o-mini")
□ REVIEWER_MODEL (e.g., "gpt-4o-mini") 
□ ANALYZER_MODEL (e.g., "gpt-4o-mini")

# Project v2 Configuration (if using project tracking):
□ GITHUB_PROJECT_ID or GH_PROJECT_ID
□ PROJECT_STATUS_FIELD_ID
□ PROJECT_STATUS_BACKLOG_ID
□ PROJECT_STATUS_INPROGRESS_ID
□ PROJECT_STATUS_INREVIEW_ID
□ PROJECT_STATUS_DONE_ID
```

**Commands to verify variables:**
```bash
# List repository variables
gh api repos/:owner/:repo/actions/variables | jq '.variables[].name'
```

## 4. Test LLM API Keys
**Run these tests to verify your LLM provider access:**

```bash
# Test OpenAI (if using)
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-3.5-turbo","messages":[{"role":"user","content":"test"}],"max_tokens":5}' \
  https://api.openai.com/v1/chat/completions
# Should return completion, not auth error

# Test Anthropic (if using)  
curl -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-3-haiku-20240307","max_tokens":5,"messages":[{"role":"user","content":"test"}]}' \
  https://api.anthropic.com/v1/messages
# Should return completion, not auth error
```