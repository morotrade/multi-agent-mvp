# Workflow Files Structure Check

## 3. Verify Workflow Files Exist and Are Correctly Configured

### Required File Structure
```bash
# Check these files exist in .github/workflows/
□ analyzer.yml
□ dev.yml  
□ reviewer.yml
□ progress.yml
```

**Commands to verify:**
```bash
# List workflow files
ls -la .github/workflows/

# Check if workflows are valid YAML
for file in .github/workflows/*.yml; do
  echo "Checking $file..."
  python -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null && echo "✓ Valid YAML" || echo "✗ Invalid YAML"
done
```

### analyzer.yml Requirements
```bash
# Check analyzer.yml contains:
□ Trigger: issues: [labeled] 
□ Condition: contains(github.event.label.name, 'bot:analyze')
□ Environment: ISSUE_NUMBER, ISSUE_BODY, ISSUE_TITLE
□ Environment: At least one LLM API key
□ Environment: GH_CLASSIC_TOKEN for project integration
```

**Verification command:**
```bash
# Check analyzer trigger
grep -A 5 "issues:" .github/workflows/analyzer.yml
grep "bot:analyze" .github/workflows/analyzer.yml
```

### dev.yml Requirements  
```bash
# Check dev.yml contains TWO jobs:

Job 1 - dev-issue:
□ Trigger: issues: [labeled]
□ Condition: contains(github.event.label.name, 'bot:implement')
□ Environment: ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY
□ Git config step included

Job 2 - dev-pr-fix:
□ Trigger: pull_request: [labeled, synchronize]
□ Condition: labeled with 'need-fix' OR synchronize event
□ Environment: PR_NUMBER (CRITICAL)
□ Checkout with token for push access
□ Git config step included
□ fetch-depth: 0
```

**Verification commands:**
```bash
# Check both jobs exist
grep "dev-issue\|dev-pr-fix" .github/workflows/dev.yml

# Check PR_NUMBER is passed
grep "PR_NUMBER" .github/workflows/dev.yml

# Check git config steps
grep -A 3 "Configure git" .github/workflows/dev.yml
```

### reviewer.yml Requirements
```bash
# Check reviewer.yml contains:
□ Trigger: pull_request: [opened, synchronize, reopened, labeled]
□ Environment: PR context (not ISSUE_NUMBER)
□ Environment: At least one LLM API key
□ Environment: GH_CLASSIC_TOKEN for project integration
```

**Verification command:**
```bash
# Check reviewer triggers
grep -A 5 "pull_request:" .github/workflows/reviewer.yml
```

### progress.yml Requirements  
```bash
# Check progress.yml contains:
□ Trigger: pull_request: [closed]
□ Condition: github.event.pull_request.merged == true
□ Environment: GH_CLASSIC_TOKEN for project integration
```

**Verification command:**
```bash
# Check progress trigger and condition
grep -A 3 "pull_request:" .github/workflows/progress.yml
grep "merged" .github/workflows/progress.yml
```

## 4. Python Files Deployment Check

### Verify Core Files Are Present
```bash
# Check all required Python files exist:
□ analyzer.py
□ dev.py
□ reviewer.py  
□ progress.py
□ utils.py

# Check for duplicates (there should be only ONE of each):
find . -name "*.py" -path "*/workflows/*" -o -name "*analyzer*" -o -name "*dev*" -o -name "*reviewer*" -o -name "*progress*" -o -name "*utils*" | wc -l
# Should match exactly the number of unique files you expect
```

**Verification commands:**
```bash
# List Python files in repository root
ls -la *.py

# Check for syntax errors
for file in *.py; do
  echo "Checking $file..."
  python -m py_compile "$file" 2>/dev/null && echo "✓ Valid syntax" || echo "✗ Syntax error"
done

# Check imports can be resolved
python -c "import analyzer, dev, reviewer, progress, utils" 2>/dev/null && echo "✓ Imports OK" || echo "✗ Import errors"
```

## 5. Dependencies Check

### Required Python Packages
```bash
# Check httpx is available (required by all scripts):
python -c "import httpx; print('httpx version:', httpx.__version__)"

# Check if additional packages are needed:
grep -r "import " *.py | grep -v "os\|json\|re\|sys\|time\|subprocess\|typing" | sort | uniq
# Review output for any packages beyond httpx that need installation
```

## 6. File Content Validation

### Critical Content Checks
```bash
# Check utils.py has all required functions:
□ extract_single_diff()
□ apply_diff_resilient() 
□ call_llm_api()
□ get_preferred_model()
□ validate_diff_files()

# Check each agent imports utils correctly:
grep "from utils import" *.py
# Should show all agents importing required functions

# Check environment variable handling:
grep "os.environ\|os.getenv" *.py | grep -E "(GITHUB_TOKEN|GH_CLASSIC_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY)"
# Should show proper env var access in all files
```

**Validation commands:**
```bash
# Check for required functions in utils.py
grep "def extract_single_diff\|def apply_diff_resilient\|def call_llm_api" utils.py

# Check all files have proper shebang and encoding
head -2 *.py | grep -E "(#!/usr/bin/env python3|# -\*- coding: utf-8 -\*-)"
```