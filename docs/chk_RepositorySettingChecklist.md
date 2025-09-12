# Repository Settings Pre-Flight Check

## 1. Actions Permissions
Navigate to: **Settings → Actions → General**

```bash
# Check these settings:
□ Actions permissions: "Allow all actions and reusable workflows"
□ Workflow permissions: "Read and write permissions" 
□ "Allow GitHub Actions to create and approve pull requests" ✓ ENABLED
```

**Commands to verify:**
```bash
# Check if Actions are enabled
gh api repos/:owner/:repo | jq '.has_github_actions_enabled'
# Should return: true

# Check workflow permissions  
gh api repos/:owner/:repo | jq '.default_branch_protection_rules'
```

## 2. Branch Protection Rules
Navigate to: **Settings → Branches**

```bash
# If you have protection rules on main branch:
□ Status checks: Make AI workflows "optional" during testing
□ OR: Allow administrators to bypass (temporary for testing)
□ OR: Disable branch protection temporarily
```

**Commands to check:**
```bash
# List branch protection rules
gh api repos/:owner/:repo/branches/main/protection
# If this returns data, you have protection rules active
```

## 3. Repository Features
Navigate to: **Settings → General**

```bash
□ Issues: Enabled
□ Pull requests: Enabled  
□ Projects: Enabled (if using Project v2)
```

**Commands to verify:**
```bash
# Check repository features
gh api repos/:owner/:repo | jq '{has_issues, has_projects, has_pull_requests}'
```