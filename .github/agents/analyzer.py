#!/usr/bin/env python3
"""
analyzer.py - Issue Analyzer (CLEAN DEDUPLICATED VERSION)
Analyzes parent issues and creates structured implementation plans with tasks
"""
import os, json, re
import httpx
from utils import (
    get_github_headers, post_issue_comment, create_issue, add_labels,
    get_issue_node_id, add_item_to_project, set_project_single_select,
    call_llm_api, get_preferred_model, resolve_project_tag, ensure_label_exists, 
    add_labels_to_issue, extract_requirements_from_issue, format_issue_summary,
    validate_environment
)

# ---------- Environment & Configuration ----------
REPO = os.environ["GITHUB_REPOSITORY"]                # "owner/repo"
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])        # parent issue id
ISSUE_BODY = os.getenv("ISSUE_BODY", "")             # issue body from env

OWNER, REPO_NAME = REPO.split("/")

# Project configuration (both aliases supported)
PROJECT_ID = (
    os.getenv("GITHUB_PROJECT_ID") or 
    os.getenv("GH_PROJECT_ID") or 
    None
)
STATUS_FIELD_ID = os.getenv("PROJECT_STATUS_FIELD_ID") or None
BACKLOG_ID = os.getenv("PROJECT_STATUS_BACKLOG_ID") or None

# ---------- Helper Functions ----------
def _get_issue():
    """Fetch the parent issue from GitHub"""
    url = f"https://api.github.com/repos/{REPO}/issues/{ISSUE_NUMBER}"
    try:
        with httpx.Client(timeout=30) as client:
            r = client.get(url, headers=get_github_headers())
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"Failed to fetch issue #{ISSUE_NUMBER}: {e}")
        raise

def load_prompt() -> str:
    """Load analyzer prompt with fallback"""
    path = ".github/prompts/analyzer.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """# Role: Senior Tech Project Planner (Analyzer)

You analyze parent Issues and produce modular implementation plans.

## Your Task
1. Break down the issue into logical implementation phases (sprints)
2. Create specific, actionable tasks for each phase
3. Estimate complexity and set appropriate labels
4. Consider dependencies between tasks

## Response Format
Return ONLY a JSON object with this structure:

```json
{
  "policy": "essential-only|strict|lenient",
  "complexity": "low|medium|high", 
  "sprints": [
    {
      "name": "Sprint 1: Foundation",
      "goal": "Set up basic structure",
      "duration": "1-2 weeks",
      "priority": "high"
    }
  ],
  "tasks": [
    {
      "title": "Implement core functionality",
      "description": "Detailed description of what needs to be done",
      "acceptance": ["Criteria 1", "Criteria 2"],
      "labels": ["feature", "backend"],
      "priority": "high|medium|low",
      "estimated_hours": 8,
      "depends_on": ["Other task names"],
      "paths": ["src/file.py", "tests/test_file.py"]
    }
  ]
}
```

Focus on creating actionable, well-defined tasks with clear acceptance criteria.
"""

def parse_llm_json(text: str) -> dict:
    """Extract and validate JSON with enhanced error handling"""
    if not text or not text.strip():
        raise Exception("Analyzer: Empty response from LLM")
    
    # Try to extract JSON block
    json_text = text.strip()
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if m:
        json_text = m.group(1)
    elif text.startswith("{"):
        # Assume raw JSON
        pass
    else:
        # Look for any JSON-like structure
        json_match = re.search(r'(\{[\s\S]*\})', text)
        if json_match:
            json_text = json_match.group(1)
        else:
            raise Exception("Analyzer: No JSON structure found in response")
    
    try:
        obj = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise Exception(f"Analyzer: Invalid JSON ({e})")

    if not isinstance(obj, dict):
        raise Exception("Analyzer: JSON root must be an object")

    # Enhanced validation and defaults
    obj.setdefault("policy", "essential-only")
    obj.setdefault("complexity", "medium")
    obj.setdefault("sprints", [])
    obj.setdefault("tasks", [])
    
    if not isinstance(obj["sprints"], list):
        raise Exception("Analyzer: 'sprints' must be a list")
    if not isinstance(obj["tasks"], list):
        raise Exception("Analyzer: 'tasks' must be a list")
    
    # Validate policy
    if obj["policy"] not in ["essential-only", "strict", "lenient"]:
        print(f"Invalid policy '{obj['policy']}', defaulting to 'essential-only'")
        obj["policy"] = "essential-only"
    
    # Validate complexity
    if obj["complexity"] not in ["low", "medium", "high"]:
        print(f"Invalid complexity '{obj['complexity']}', defaulting to 'medium'")
        obj["complexity"] = "medium"
    
    return obj

def validate_issue_content(issue_data: dict) -> dict:
    """Validate and analyze issue content"""
    title = issue_data.get("title", "")
    body = issue_data.get("body", "")
    
    if not title.strip():
        raise Exception("Issue must have a non-empty title")
    
    # Extract structured requirements
    requirements = extract_requirements_from_issue(body)
    project_tag = resolve_project_tag(body)
    
    # Analyze complexity heuristics
    complexity_indicators = {
        "high": ["migration", "refactor", "architecture", "performance", "security", "integration"],
        "medium": ["feature", "enhancement", "api", "database", "ui"],
        "low": ["bug", "fix", "typo", "documentation", "config"]
    }
    
    detected_complexity = "low"
    title_lower = title.lower()
    body_lower = body.lower()
    combined_text = f"{title_lower} {body_lower}"
    
    for level, indicators in complexity_indicators.items():
        if any(indicator in combined_text for indicator in indicators):
            detected_complexity = level
            break
    
    return {
        "title": title,
        "body": body,
        "requirements": requirements,
        "project_tag": project_tag,
        "detected_complexity": detected_complexity,
        "has_acceptance_criteria": bool(requirements["acceptance"]),
        "has_file_paths": bool(requirements["files"]),
        "has_dependencies": bool(requirements["dependencies"])
    }

def add_to_project_if_available(issue_number: int, status_option_id: str | None) -> bool:
    """Link issue to Project with enhanced error handling"""
    if not PROJECT_ID:
        print("Project integration disabled (no PROJECT_ID)")
        return False
    
    try:
        node_id = get_issue_node_id(OWNER, REPO_NAME, issue_number)
        item_id = add_item_to_project(PROJECT_ID, node_id)
        
        if STATUS_FIELD_ID and status_option_id:
            set_project_single_select(PROJECT_ID, item_id, STATUS_FIELD_ID, status_option_id)
            
        print(f"Issue #{issue_number} linked to project")
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "scope" in error_msg.lower() or "permission" in error_msg.lower():
            post_issue_comment(
                OWNER, REPO_NAME, ISSUE_NUMBER,
                f"Project linking requires GH_CLASSIC_TOKEN with 'project' scope. "
                f"Issue #{issue_number} created but not linked to project."
            )
        else:
            post_issue_comment(
                OWNER, REPO_NAME, ISSUE_NUMBER,
                f"Project linking failed for #{issue_number}: `{e}`"
            )
        print(f"Project linking failed: {e}")
        return False

def create_enhanced_prompt(issue_analysis: dict) -> str:
    """Create enhanced prompt with issue analysis"""
    base_prompt = load_prompt()
    
    # Add context from issue analysis
    context_section = f"""
## Issue Analysis
- **Complexity**: {issue_analysis['detected_complexity']}
- **Has Acceptance Criteria**: {issue_analysis['has_acceptance_criteria']}
- **Has File Paths**: {issue_analysis['has_file_paths']}
- **Has Dependencies**: {issue_analysis['has_dependencies']}

## Issue Details
**Title**: {issue_analysis['title']}

**Requirements Summary**:
{format_issue_summary({'title': issue_analysis['title'], 'body': issue_analysis['body']})}

**Full Description**:
{issue_analysis['body']}
"""
    
    return f"{base_prompt}\n{context_section}"

# ---------- Main Function ----------
def main():
    print("Analyzer: Enhanced version starting...")
    
    # Environment validation
    env_checks = validate_environment()
    missing_requirements = [key for key, value in env_checks.items() if not value and key != 'classic_token']
    
    if missing_requirements:
        error_msg = f"Missing requirements: {', '.join(missing_requirements)}"
        print(error_msg)
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, error_msg)
        return 1
    
    # Fetch and validate issue
    try:
        issue = _get_issue()
        issue_analysis = validate_issue_content(issue)
        print(f"Issue analysis complete: complexity={issue_analysis['detected_complexity']}")
    except Exception as e:
        error_msg = f"Issue validation failed: {e}"
        print(error_msg)
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, error_msg)
        return 1

    # Apply project tag if found
    project_tag = issue_analysis["project_tag"]
    if project_tag:
        try:
            ensure_label_exists(OWNER, REPO_NAME, project_tag, color="0E8A16", 
                              description=f"Project tag: {project_tag}")
            add_labels_to_issue(OWNER, REPO_NAME, ISSUE_NUMBER, [project_tag])
            print(f"Applied project tag: {project_tag}")
        except Exception as e:
            print(f"Project tag application failed: {e}")

    # Post initial status
    post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, 
                      f"Analyzer started for issue #{ISSUE_NUMBER}\n"
                      f"Repository: {REPO}\n"
                      f"Model: {get_preferred_model('analyzer')}\n"
                      f"Project Integration: {'enabled' if PROJECT_ID else 'disabled'}\n"
                      f"Issue Complexity: {issue_analysis['detected_complexity']}")

    # Generate implementation plan
    try:
        prompt = create_enhanced_prompt(issue_analysis)
        model = get_preferred_model("analyzer")
        
        print(f"Generating plan with {model}...")
        raw_response = call_llm_api(prompt, model=model, max_tokens=4000)
        
        if "error:" in raw_response.lower():
            raise Exception(f"LLM returned error: {raw_response[:200]}")
            
        plan = parse_llm_json(raw_response)
        print("Plan generated and validated")
        
    except Exception as e:
        error_msg = f"Plan generation failed: {e}"
        print(error_msg)
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, error_msg)
        return 1

    # Extract plan components
    policy = plan.get("policy", "essential-only")
    complexity = plan.get("complexity", issue_analysis["detected_complexity"])
    sprints = plan.get("sprints", [])
    tasks = plan.get("tasks", [])

    # Apply policy and complexity labels
    policy_label = f"policy:{policy}"
    complexity_label = f"complexity:{complexity}"
    
    try:
        ensure_label_exists(OWNER, REPO_NAME, policy_label, color="1f77b4", 
                          description=f"Review policy: {policy}")
        ensure_label_exists(OWNER, REPO_NAME, complexity_label, color="ff7f0e", 
                          description=f"Estimated complexity: {complexity}")
        add_labels_to_issue(OWNER, REPO_NAME, ISSUE_NUMBER, [policy_label, complexity_label])
        print(f"Applied labels: {policy_label}, {complexity_label}")
    except Exception as e:
        print(f"Label application failed: {e}")

    # Create sprint if specified
    sprint_issue_num = None
    if sprints:
        try:
            s0 = sprints[0]
            sprint_title = f"[Sprint] {s0.get('name', 'Sprint 1')}"
            sprint_body = f"""**Goal**: {s0.get('goal', 'Implementation phase')}
**Duration**: {s0.get('duration', 'TBD')}
**Priority**: {s0.get('priority', 'medium')}

**Parent Issue**: #{ISSUE_NUMBER}

This sprint contains the initial implementation tasks for the parent issue.
"""
            
            sprint = create_issue(OWNER, REPO_NAME, sprint_title, sprint_body, 
                                labels=["sprint", f"priority:{s0.get('priority', 'medium')}"])
            sprint_issue_num = sprint["number"]
            
            post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, 
                             f"Created sprint: #{sprint_issue_num} — {sprint_title}")
            
            # Link sprint to project
            add_to_project_if_available(sprint_issue_num, BACKLOG_ID)
            print(f"Sprint created: #{sprint_issue_num}")
            
        except Exception as e:
            print(f"Sprint creation failed: {e}")

    # Create tasks
    created_tasks = []
    failed_tasks = []
    
    for i, task in enumerate(tasks, 1):
        try:
            task_title = task.get("title") or f"Task {i}"
            
            # Build description
            desc_parts = []
            if task.get("description"):
                desc_parts.append(task["description"])
            
            if task.get("acceptance"):
                desc_parts.append("\n**Acceptance Criteria**:")
                desc_parts.extend(f"- {criteria}" for criteria in task["acceptance"])
            
            if task.get("paths"):
                desc_parts.append("\n**Files to modify**:")
                desc_parts.extend(f"- `{path}`" for path in task["paths"])
            
            if task.get("depends_on"):
                desc_parts.append("\n**Dependencies**:")
                desc_parts.extend(f"- {dep}" for dep in task["depends_on"])
            
            if task.get("estimated_hours"):
                desc_parts.append(f"\n**Estimated effort**: {task['estimated_hours']} hours")
            
            task_body = "\n".join(desc_parts).strip() or f"Implementation task from #{ISSUE_NUMBER}"
            task_body += f"\n\n**Parent**: #{ISSUE_NUMBER}"
            
            # Prepare labels
            task_labels = list(set((task.get("labels") or []) + ["task"]))
            if task.get("priority"):
                task_labels.append(f"priority:{task['priority']}")
            
            # Create task issue
            task_issue = create_issue(OWNER, REPO_NAME, task_title, task_body, labels=task_labels)
            task_num = task_issue["number"]
            created_tasks.append(task_num)
            
            # Link to project
            add_to_project_if_available(task_num, BACKLOG_ID)
            
        except Exception as e:
            print(f"Task {i} creation failed: {e}")
            failed_tasks.append(i)

    # Auto-start the first task
    if created_tasks:
        try:
            first_task = created_tasks[0]
            add_labels(OWNER, REPO_NAME, first_task, ["bot:implement"])
            print(f"Auto-started first task: #{first_task}")
        except Exception as e:
            post_issue_comment(
                OWNER, REPO_NAME, ISSUE_NUMBER,
                f"Could not auto-start task #{created_tasks[0]}: `{e}`"
            )

    # Final summary
    summary_parts = [
        "Analysis Complete",
        f"Policy: {policy}",
        f"Complexity: {complexity}",
        f"Sprints created: {1 if sprint_issue_num else 0}",
        f"Tasks created: {len(created_tasks)}",
    ]
    
    if failed_tasks:
        summary_parts.append(f"Failed tasks: {len(failed_tasks)}")
    
    if created_tasks:
        summary_parts.extend([
            "",
            "Next Steps:",
            f"- First task #{created_tasks[0]} is auto-labeled for `bot:implement`",
            "- Add `bot:implement` label to other tasks to trigger development",
            "- Tasks will be processed sequentially as PRs are completed"
        ])
    
    if not env_checks["classic_token"]:
        summary_parts.extend([
            "",
            "Note: Set `GH_CLASSIC_TOKEN` for full project integration"
        ])
    
    summary_message = "\n".join(summary_parts)
    post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, summary_message)
    
    print(f"Analysis complete: {len(created_tasks)} tasks created")
    return 0

if __name__ == "__main__":
    exit(main())