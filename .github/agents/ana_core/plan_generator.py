#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Implementation plan generation using LLM for AI Analyzer
"""
import json
import re
import os
from typing import Dict, Optional

from utils.llm_providers import call_llm_api, get_preferred_model


class PlanGenerator:
    """Handles LLM-based implementation plan generation with robust parsing"""
    
    def __init__(self, model: Optional[str] = None, max_tokens: int = 4000):
        self.model = model or get_preferred_model("analyzer")
        self.max_tokens = max_tokens
    
    def load_prompt_template(self) -> str:
        """Load analyzer prompt with fallback to default"""
        path = ".github/prompts/analyzer.md"
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return self._get_default_prompt_template()
    
    def _get_default_prompt_template(self) -> str:
        """Default prompt template for implementation planning"""
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
    
    def create_enhanced_prompt(self, issue_analysis: Dict) -> str:
        """Create enhanced prompt with issue analysis context"""
        base_prompt = self.load_prompt_template()
        
        # Build context section with analysis results
        context_section = f"""
## Issue Analysis Context
- **Complexity Detected**: {issue_analysis['detected_complexity']}
- **Final Complexity**: {issue_analysis.get('final_complexity', 'medium')}
- **Complexity Score**: {issue_analysis.get('complexity_score', 'N/A')}
- **Has Acceptance Criteria**: {issue_analysis['has_acceptance_criteria']}
- **Has File Paths**: {issue_analysis['has_file_paths']}
- **Has Dependencies**: {issue_analysis['has_dependencies']}

## Issue Details
**Title**: {issue_analysis['title']}

**Requirements Summary**:
{issue_analysis.get('formatted_summary', 'No summary available')}

**Full Description**:
{issue_analysis['body']}

## Planning Guidelines
- Use the detected complexity ({issue_analysis['detected_complexity']}) as a starting point
- Create {self._suggest_task_count(issue_analysis)} tasks based on complexity
- Consider existing file paths: {', '.join(issue_analysis['requirements'].get('files', [])[:5])}
- Factor in dependencies: {', '.join(issue_analysis['requirements'].get('dependencies', [])[:3])}
"""
        
        return f"{base_prompt}\n{context_section}"
    
    def _suggest_task_count(self, analysis: Dict) -> str:
        """Suggest appropriate number of tasks based on complexity"""
        complexity = analysis.get('final_complexity', analysis['detected_complexity'])
        
        if complexity == "low":
            return "1-2"
        elif complexity == "medium":
            return "2-4"
        else:  # high
            return "3-6"
    
    def parse_llm_json(self, raw_response: str) -> Dict:
        """
        Extract and validate JSON from LLM response with enhanced error handling.
        Supports both fenced and naked JSON formats.
        """
        if not raw_response or not raw_response.strip():
            raise ValueError("Analyzer: Empty response from LLM")
        
        # Try different JSON extraction strategies
        json_text = self._extract_json_text(raw_response)
        
        try:
            obj = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Analyzer: Invalid JSON - {e}")
        
        if not isinstance(obj, dict):
            raise ValueError("Analyzer: JSON root must be an object")
        
        # Validate and normalize the plan structure
        return self._validate_and_normalize_plan(obj)
    
    def _extract_json_text(self, raw_response: str) -> str:
        """Extract JSON text from various formats"""
        text = raw_response.strip()
        
        # Strategy 1: Extract from fenced code block
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
        if json_match:
            return json_match.group(1)
        
        # Strategy 2: Extract from any code block
        code_match = re.search(r"```\s*([\s\S]+?)\s*```", text)
        if code_match:
            candidate = code_match.group(1)
            if candidate.strip().startswith("{"):
                return candidate
        
        # Strategy 3: Look for JSON-like structure
        if text.startswith("{"):
            return text
        
        # Strategy 4: Find any JSON object in the text
        # Non-greedy per il primo oggetto plausibile
        json_pattern = re.search(r'(\{[\s\S]*?\})', text)
        if json_pattern:
            return json_pattern.group(1)
        
        # Fallback: scanner bilanciato grezzo
        start = text.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth = 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i+1]
        
        raise ValueError("No JSON structure found in LLM response")
    
    def _validate_and_normalize_plan(self, obj: Dict) -> Dict:
        """Validate and normalize plan structure with sensible defaults"""
        # Apply defaults
        obj.setdefault("policy", "essential-only")
        obj.setdefault("complexity", "medium")
        obj.setdefault("sprints", [])
        obj.setdefault("tasks", [])
        
        # Validate types
        if not isinstance(obj["sprints"], list):
            raise ValueError("'sprints' must be a list")
        if not isinstance(obj["tasks"], list):
            raise ValueError("'tasks' must be a list")
        
        # Validate and normalize policy
        valid_policies = ["essential-only", "strict", "lenient"]
        if obj["policy"] not in valid_policies:
            print(f"Invalid policy '{obj['policy']}', defaulting to 'essential-only'")
            obj["policy"] = "essential-only"
        
        # Validate and normalize complexity
        valid_complexities = ["low", "medium", "high"]
        if obj["complexity"] not in valid_complexities:
            print(f"Invalid complexity '{obj['complexity']}', defaulting to 'medium'")
            obj["complexity"] = "medium"
        
        # Validate tasks structure
        obj["tasks"] = self._normalize_tasks(obj["tasks"])
        
        # Validate sprints structure
        obj["sprints"] = self._normalize_sprints(obj["sprints"])
        
        return obj
    
    def _normalize_tasks(self, tasks: list) -> list:
        """Normalize and validate task structures"""
        normalized = []
        
        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                print(f"Skipping invalid task {i + 1} (not a dict)")
                continue
            
            # Ensure required fields
            normalized_task = {
                "title": str(task.get("title", f"Task {i + 1}")),
                "description": str(task.get("description", "No description provided")),
                "acceptance": list(task.get("acceptance", [])),
                "labels": list(task.get("labels", ["task"])),
                "priority": task.get("priority", "medium"),
                "estimated_hours": self._safe_hours(task.get("estimated_hours", 4)),
                "depends_on": list(task.get("depends_on", [])),
                "paths": list(task.get("paths", []))
            }
            
            # Validate priority
            if normalized_task["priority"] not in ["low", "medium", "high"]:
                normalized_task["priority"] = "medium"
            
            # Ensure reasonable hour estimates
            if normalized_task["estimated_hours"] < 1:
                normalized_task["estimated_hours"] = 1
            elif normalized_task["estimated_hours"] > 80:
                normalized_task["estimated_hours"] = 80
            
            normalized.append(normalized_task)
        
        return normalized
    
    def _safe_hours(self, value) -> int:
        """Coercizione 'safe' per estimated_hours con clamp 1..80."""
        try:
            if isinstance(value, (int, float)):
                hours = int(value)
            else:
                # Estrai la prima sequenza numerica, es. "8h" -> 8, "~6" -> 6
                import re
                m = re.search(r"\d+", str(value))
                hours = int(m.group(0)) if m else 4
        except Exception:
            hours = 4
        # Clamp ragionevole
        return max(1, min(hours, 80))
    
    def _normalize_sprints(self, sprints: list) -> list:
        """Normalize and validate sprint structures"""
        normalized = []
        
        for i, sprint in enumerate(sprints):
            if not isinstance(sprint, dict):
                print(f"Skipping invalid sprint {i + 1} (not a dict)")
                continue
            
            normalized_sprint = {
                "name": str(sprint.get("name", f"Sprint {i + 1}")),
                "goal": str(sprint.get("goal", "Implementation phase")),
                "duration": str(sprint.get("duration", "1-2 weeks")),
                "priority": sprint.get("priority", "medium")
            }
            
            # Validate priority
            if normalized_sprint["priority"] not in ["low", "medium", "high"]:
                normalized_sprint["priority"] = "medium"
            
            normalized.append(normalized_sprint)
        
        return normalized
    
    def generate_implementation_plan(self, issue_analysis: Dict) -> Dict:
        """
        Generate implementation plan using LLM.
        Returns validated and normalized plan structure.
        """
        prompt = self.create_enhanced_prompt(issue_analysis)
        
        print(f"Generating implementation plan with {self.model}...")
        
        try:
            raw_response = call_llm_api(prompt, model=self.model, max_tokens=self.max_tokens)
            
            # Check for obvious errors in response
            if "error:" in raw_response.lower():
                raise RuntimeError(f"LLM returned error: {raw_response[:200]}")
            
            plan = self.parse_llm_json(raw_response)
            
            # Add metadata
            plan["_metadata"] = {
                "model_used": self.model,
                "issue_complexity": issue_analysis.get('final_complexity', 'medium'),
                "task_count": len(plan.get("tasks", [])),
                "sprint_count": len(plan.get("sprints", []))
            }
            
            print(f"Plan generated successfully: {len(plan['tasks'])} tasks, {len(plan['sprints'])} sprints")
            return plan
            
        except Exception as e:
            raise RuntimeError(f"Plan generation failed: {e}")
    
    def estimate_total_effort(self, plan: Dict) -> int:
        """Calculate total estimated effort in hours"""
        return sum(task.get("estimated_hours", 4) for task in plan.get("tasks", []))
    
    def analyze_task_dependencies(self, plan: Dict) -> Dict:
        """Analyze task dependencies and suggest execution order"""
        tasks = plan.get("tasks", [])
        task_names = {task["title"] for task in tasks}
        
        dependency_analysis = {
            "has_dependencies": False,
            "circular_dependencies": [],
            "suggested_order": [],
            "independent_tasks": [],
            "dependent_tasks": [],
            "unknown_dependencies": []
        }
        
        # Check for dependencies
        for task in tasks:
            depends_on = task.get("depends_on", [])
            if depends_on:
                dependency_analysis["has_dependencies"] = True
                dependency_analysis["dependent_tasks"].append(task["title"])
                
                # Check for circular dependencies (simple check)
                for dep in depends_on:
                    if dep not in task_names:
                        msg = f"Task '{task['title']}' depends on unknown task '{dep}'"
                        print(f"Warning: {msg}")
                        dependency_analysis["unknown_dependencies"].append(msg)
            else:
                dependency_analysis["independent_tasks"].append(task["title"])
        
        # Simple topological sort for suggested order
        remaining_tasks = tasks.copy()
        ordered_tasks = []
        
        while remaining_tasks:
            # Find tasks with no unresolved dependencies
            ready_tasks = []
            for task in remaining_tasks:
                depends_on = task.get("depends_on", [])
                resolved_deps = all(dep in [t["title"] for t in ordered_tasks] for dep in depends_on)
                if resolved_deps:
                    ready_tasks.append(task)
            
            if not ready_tasks:
                # Circular dependency or unresolvable
                dependency_analysis["suggested_order"] = [t["title"] for t in ordered_tasks]
                dependency_analysis["circular_dependencies"] = [t["title"] for t in remaining_tasks]
                break
            
            # Add ready tasks to order
            ordered_tasks.extend(ready_tasks)
            for task in ready_tasks:
                remaining_tasks.remove(task)
        
        if not dependency_analysis["circular_dependencies"]:
            dependency_analysis["suggested_order"] = [t["title"] for t in ordered_tasks]
        
        return dependency_analysis
