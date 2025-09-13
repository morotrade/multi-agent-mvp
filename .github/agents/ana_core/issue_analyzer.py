#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue analysis and validation for AI Analyzer
"""
from typing import Dict, Tuple

from utils.github_api import get_issue, get_repo_info
from utils.issue_parsing import extract_requirements_from_issue, resolve_project_tag, format_issue_summary


class IssueAnalyzer:
    """Handles issue fetching, validation, and analysis"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
    
    def fetch_issue(self, issue_number: int) -> Dict:
        """Fetch issue from GitHub API"""
        try:
            return get_issue(self.owner, self.repo, issue_number)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch issue #{issue_number}: {e}")
    
    def validate_issue_content(self, issue_data: Dict) -> Dict:
        """
        Validate and analyze issue content for implementation planning.
        Returns enriched analysis with complexity detection and requirements.
        """
        title = issue_data.get("title", "")
        body = issue_data.get("body", "")
        
        if not title.strip():
            raise ValueError("Issue must have a non-empty title")
        
        # Extract structured requirements using utils
        requirements = extract_requirements_from_issue(body)
        project_tag = resolve_project_tag(body)
        
        # Detect complexity using heuristics
        complexity = self._detect_complexity(title, body)
        
        return {
            "title": title,
            "body": body,
            "requirements": requirements,
            "project_tag": project_tag,
            "detected_complexity": complexity,
            "has_acceptance_criteria": bool(requirements["acceptance"]),
            "has_file_paths": bool(requirements["files"]),
            "has_dependencies": bool(requirements["dependencies"]),
            "formatted_summary": format_issue_summary(issue_data)
        }
    
    def _detect_complexity(self, title: str, body: str) -> str:
        """
        Detect issue complexity using keyword analysis.
        Returns: 'low', 'medium', or 'high'
        """
        complexity_indicators = {
            "high": [
                "migration", "refactor", "architecture", "performance", 
                "security", "integration", "system", "infrastructure",
                "database migration", "api overhaul", "major rewrite"
            ],
            "medium": [
                "feature", "enhancement", "api", "database", "ui", "ux",
                "new functionality", "component", "service", "module",
                "improvement", "optimization"
            ],
            "low": [
                "bug", "fix", "typo", "documentation", "config", "update",
                "minor", "small", "simple", "quick", "patch"
            ]
        }
        
        combined_text = f"{title} {body}".lower()
        
        # Check from most specific to least specific
        for complexity_level in ["high", "medium", "low"]:
            indicators = complexity_indicators[complexity_level]
            if any(indicator in combined_text for indicator in indicators):
                return complexity_level
        
        # Default to medium if no indicators found
        return "medium"
    
    def calculate_complexity_score(self, issue_analysis: Dict) -> Tuple[str, int]:
        """
        Calculate complexity score based on multiple factors.
        Returns (complexity_level, numerical_score)
        """
        score = 0
        factors = []
        
        # Base complexity from keyword detection
        base_complexity = issue_analysis["detected_complexity"]
        complexity_scores = {"low": 1, "medium": 3, "high": 5}
        score += complexity_scores[base_complexity]
        factors.append(f"keyword analysis: {base_complexity}")
        
        # Requirements completeness factor
        if issue_analysis["has_acceptance_criteria"]:
            factors.append("has acceptance criteria")
        else:
            score += 1  # Missing criteria adds complexity
            factors.append("missing acceptance criteria (+1)")
        
        if issue_analysis["has_file_paths"]:
            factors.append("has file paths specified")
        else:
            score += 1  # Unknown file scope adds complexity
            factors.append("unspecified file scope (+1)")
        
        if issue_analysis["has_dependencies"]:
            score += 2  # Dependencies increase complexity
            factors.append("has dependencies (+2)")
        
        # Text length factor (longer descriptions often mean more complexity)
        body_length = len(issue_analysis["body"])
        if body_length > 2000:
            score += 2
            factors.append("extensive description (+2)")
        elif body_length > 1000:
            score += 1
            factors.append("detailed description (+1)")
        
        # Map final score to complexity level
        if score <= 2:
            final_complexity = "low"
        elif score <= 5:
            final_complexity = "medium"
        else:
            final_complexity = "high"
        
        return final_complexity, score
    
    def analyze_issue_comprehensive(self, issue_number: int) -> Dict:
        """
        Perform comprehensive analysis of an issue.
        Combines fetching, validation, and complexity analysis.
        """
        # Fetch issue data
        issue_data = self.fetch_issue(issue_number)
        
        # Validate and extract structure
        analysis = self.validate_issue_content(issue_data)
        
        # Enhanced complexity analysis
        complexity_level, complexity_score = self.calculate_complexity_score(analysis)
        analysis["complexity_score"] = complexity_score
        analysis["final_complexity"] = complexity_level
        
        # Add metadata
        analysis["issue_number"] = issue_number
        analysis["issue_url"] = issue_data.get("html_url", "")
        analysis["created_at"] = issue_data.get("created_at", "")
        analysis["updated_at"] = issue_data.get("updated_at", "")
        
        return analysis
    
    def get_analysis_summary(self, analysis: Dict) -> str:
        """Generate human-readable summary of issue analysis"""
        lines = []
        lines.append(f"Issue #{analysis['issue_number']}: {analysis['title']}")
        lines.append(f"Complexity: {analysis['final_complexity'].upper()} (score: {analysis['complexity_score']})")
        
        if analysis['project_tag']:
            lines.append(f"Project: {analysis['project_tag']}")
        
        capabilities = []
        if analysis['has_acceptance_criteria']:
            capabilities.append("acceptance criteria defined")
        if analysis['has_file_paths']:
            capabilities.append("file paths specified")
        if analysis['has_dependencies']:
            capabilities.append("dependencies identified")
        
        if capabilities:
            lines.append(f"Capabilities: {', '.join(capabilities)}")
        
        return " | ".join(lines)
