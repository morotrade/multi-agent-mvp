# System Integration Test Commands

## 7. End-to-End Connectivity Tests

### Test GitHub API Access
```bash
# Test basic GitHub API access
gh auth status
# Should show: ✓ Logged in to github.com as [username]

# Test repository access
gh repo view --json name,hasIssuesEnabled,hasProjectsEnabled
# Should return repository info without errors

# Test Actions access
gh run list --limit 1
# Should list recent workflow runs
```

### Test GraphQL Project Access (Critical)
```bash
# Test GraphQL endpoint access
gh api graphql -f query='query{viewer{login}}'
# Should return your username

# Test Project v2 access (most critical test)
gh api graphql -f query='query{viewer{projectsV2(first:3){nodes{id title}}}}'
# Should return projects without "insufficient_scopes" error
# If error: your GH_CLASSIC_TOKEN lacks 'project' scope

# Test specific project access (if you have PROJECT_ID)
PROJECT_ID="your_project_id_here"
gh api graphql -f query="query{node(id:\"$PROJECT_ID\"){...on ProjectV2{title}}}"
# Should return project title
```

### Test File System Permissions
```bash
# Test git operations (simulates what dev.py does)
git config --global user.name "Test User"
git config --global user.email "test@example.com"
git status
# Should work without permission errors

# Test file creation in allowed paths
touch test_file.py
echo "# test" > test_file.py
rm test_file.py
# Should work without errors

# Test Python execution
python --version
python -c "import sys; print('Python OK')"
```

## 8. Workflow Syntax Validation

### Validate All Workflow Files
```bash
# Check workflow syntax using act (if installed) or manual validation
for workflow in .github/workflows/*.yml; do
  echo "Validating $workflow..."
  
  # Basic YAML syntax check
  python -c "
import yaml
try:
    with open('$workflow') as f:
        yaml.safe_load(f)
    print('✓ Valid YAML syntax')
except Exception as e:
    print('✗ YAML error:', e)
  "
  
  # Check for required GitHub Actions syntax
  grep -q "on:" "$workflow" && echo "✓ Has triggers" || echo "✗ Missing triggers"
  grep -q "jobs:" "$workflow" && echo "✓ Has jobs" || echo "✗ Missing jobs"
  grep -q "runs-on:" "$workflow" && echo "✓ Has runner" || echo "✗ Missing runner"
done
```

### Test Workflow Trigger Logic
```bash
# Test analyzer workflow trigger
echo "Testing analyzer trigger logic..."
grep -A 10 "if:" .github/workflows/analyzer.yml | grep "bot:analyze"
# Should find the label condition

# Test dev workflow triggers (both jobs)
echo "Testing dev workflow triggers..."
grep -A 5 "if:" .github/workflows/dev.yml
# Should show both issue and PR conditions

# Test reviewer workflow trigger
echo "Testing reviewer trigger..."
grep -A 5 "pull_request:" .github/workflows/reviewer.yml
# Should show PR event types
```

## 9. Environment Variables Mock Test

### Simulate Workflow Environment
```bash
# Create test environment to simulate GitHub Actions
export GITHUB_REPOSITORY="owner/repo"
export GITHUB_TOKEN="test_token"
export ISSUE_NUMBER="1"
export ISSUE_TITLE="Test Issue"
export ISSUE_BODY="Test issue body"

# Test Python imports and basic functionality
python -c "
import os
print('Repository:', os.environ.get('GITHUB_REPOSITORY'))
print('Issue Number:', os.environ.get('ISSUE_NUMBER'))

# Test utils import
try:
    from utils import get_preferred_model, validate_environment
    print('✓ Utils import successful')
    print('Default model:', get_preferred_model('analyzer'))
except Exception as e:
    print('✗ Utils import failed:', e)
"

# Clean up test environment
unset GITHUB_REPOSITORY GITHUB_TOKEN ISSUE_NUMBER ISSUE_TITLE ISSUE_BODY
```

## 10. Pre-Test Issue Template

### Create Test Issue
```bash
# Use this content for your test issue:
TITLE="Add calculator package with CLI and tests"

BODY="Project: calc_v1

## Description
Create a simple calculator package with command-line interface and comprehensive tests.

## Acceptance Criteria
- Calculator supports basic operations (add, subtract, multiply, divide)
- Command-line interface accepts arguments
- Unit tests cover all functions
- Package is installable via pip
- Documentation includes usage examples

## Files to modify
- \`calc/__init__.py\`
- \`calc/calculator.py\`
- \`calc/cli.py\`
- \`tests/test_calculator.py\`
- \`setup.py\`
- \`README.md\`

## Dependencies
- No external dependencies for core functionality
- pytest for testing"

# Create the test issue
gh issue create --title "$TITLE" --body "$BODY"
echo "Test issue created. Note the issue number for next steps."
```

## 11. Quick Health Check Script

### Run This Before Testing
```bash
#!/bin/bash
# Save as check_health.sh and run before testing

echo "🔍 AI Workflow System Health Check"
echo "=================================="

# Check repository structure
echo "📁 Repository Structure:"
ls -la *.py 2>/dev/null | wc -l | xargs echo "Python files:"
ls -la .github/workflows/*.yml 2>/dev/null | wc -l | xargs echo "Workflow files:"

# Check secrets (without revealing values)
echo -e "\n🔐 Secrets Check:"
gh api repos/:owner/:repo/actions/secrets 2>/dev/null | jq -r '.secrets[].name' | while read secret; do
  echo "✓ $secret"
done

# Check Python syntax
echo -e "\n🐍 Python Syntax Check:"
for file in *.py; do
  if python -m py_compile "$file" 2>/dev/null; then
    echo "✓ $file"
  else
    echo "✗ $file (syntax error)"
  fi
done

# Check workflow syntax
echo -e "\n⚙️  Workflow Syntax Check:"
for workflow in .github/workflows/*.yml; do
  if python -c "import yaml; yaml.safe_load(open('$workflow'))" 2>/dev/null; then
    echo "✓ $(basename $workflow)"
  else
    echo "✗ $(basename $workflow) (YAML error)"
  fi
done

# Check GitHub CLI access
echo -e "\n🔗 GitHub Access Check:"
if gh auth status &>/dev/null; then
  echo "✓ GitHub CLI authenticated"
  if gh api graphql -f query='query{viewer{login}}' &>/dev/null; then
    echo "✓ GraphQL access working"
  else
    echo "✗ GraphQL access failed"
  fi
else
  echo "✗ GitHub CLI not authenticated"
fi

echo -e "\n🎯 Ready for testing!"
```

## Summary Checklist

Before running the end-to-end test, ensure all these checks pass:

```bash
□ Repository settings: Actions enabled, workflow permissions set
□ Secrets: GH_CLASSIC_TOKEN + at least one LLM API key
□ PAT scopes: repo, workflow, project, read:org
□ Workflow files: All 4 files present with correct triggers
□ Python files: All 5 files present with no syntax errors
□ GraphQL access: Project v2 API accessible
□ Git configuration: User name/email set for commits
□ Dependencies: httpx available
□ Branch protection: Disabled or bypassed for testing
```

Run the health check script, fix any issues it identifies, then proceed with the end-to-end test using the test issue template.