#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detailed report builder for AI Analyzer execution plans
"""
from typing import Dict, List


class ReportBuilder:
    """Creates detailed pre-execution reports for implementation plans"""
    
    def __init__(self):
        pass
    
    def create_detailed_report(self, plan: Dict, issue_analysis: Dict) -> str:
        """
        Create comprehensive pre-execution report with all analysis details.
        
        Args:
            plan: Generated implementation plan from LLM
            issue_analysis: Issue analysis results
            
        Returns:
            Formatted markdown report
        """
        sections = []
        
        # Header
        sections.append(self._create_header(issue_analysis))
        
        # Request analysis
        sections.append(self._create_request_analysis(plan, issue_analysis))
        
        # Complexity evaluation
        sections.append(self._create_complexity_evaluation(plan, issue_analysis))
        
        # Implementation strategy
        sections.append(self._create_implementation_strategy(plan, issue_analysis))
        
        # Segmentation plan
        sections.append(self._create_segmentation_plan(plan))
        
        # Task breakdown
        sections.append(self._create_task_breakdown(plan))
        
        # Execution sequence and risks
        sections.append(self._create_execution_sequence(plan))
        sections.append(self._create_risk_analysis(plan, issue_analysis))
        
        # Footer
        sections.append(self._create_footer())
        
        return "\n\n".join(sections)
    
    def _create_header(self, issue_analysis: Dict) -> str:
        """Create report header"""
        return "# 🎯 PIANO D'ATTACCO - Analisi Pre-Esecuzione\n"
    
    def _create_request_analysis(self, plan: Dict, issue_analysis: Dict) -> str:
        """Create request analysis section"""
        lines = []
        lines.append("## 📋 Analisi della Richiesta")
        lines.append(f"**Titolo**: {issue_analysis['title']}")
        
        complexity = plan.get("complexity", issue_analysis.get("final_complexity", "medium"))
        lines.append(f"**Complessità Rilevata**: {complexity.upper()}")
        
        policy = plan.get("policy", "essential-only")
        lines.append(f"**Policy di Review**: {policy}")
        
        # Capability indicators
        capabilities = self._analyze_capabilities(issue_analysis)
        lines.extend(capabilities)
        
        return "\n".join(lines)
    
    def _analyze_capabilities(self, issue_analysis: Dict) -> List[str]:
        """Analyze issue capabilities and completeness"""
        capabilities = []
        
        if issue_analysis['has_acceptance_criteria']:
            capabilities.append("✅ Criteri di accettazione definiti")
        else:
            capabilities.append("⚠️ Criteri di accettazione da definire")
        
        if issue_analysis['has_file_paths']:
            capabilities.append("✅ File path specificati")
        else:
            capabilities.append("🔍 File path da determinare")
        
        if issue_analysis['has_dependencies']:
            capabilities.append("🔗 Dipendenze identificate")
        else:
            capabilities.append("🆓 Nessuna dipendenza esterna")
        
        return capabilities
    
    def _create_complexity_evaluation(self, plan: Dict, issue_analysis: Dict) -> str:
        """Create complexity evaluation section"""
        lines = []
        lines.append("## 🧠 Valutazione della Complessità")
        
        complexity = plan.get("complexity", issue_analysis.get("final_complexity", "medium"))
        lines.append(f"**Grado**: {complexity.upper()}")
        
        # Complexity descriptions
        complexity_details = {
            "low": "Implementazione semplice, rischi minimi, principalmente configurazione o fix",
            "medium": "Feature moderata, richiede design e test, rischi controllabili",
            "high": "Refactor significativo, alto impatto, richiede planning accurato"
        }
        
        lines.append(f"**Valutazione**: {complexity_details.get(complexity, 'Complessità non classificata')}")
        
        # Add complexity score if available
        if 'complexity_score' in issue_analysis:
            lines.append(f"**Score Calcolato**: {issue_analysis['complexity_score']}/10")
        
        # Estimate total effort
        total_hours = sum(task.get("estimated_hours", 4) for task in plan.get("tasks", []))
        lines.append(f"**Effort Stimato**: ~{total_hours} ore totali")
        
        return "\n".join(lines)
    
    def _create_implementation_strategy(self, plan: Dict, issue_analysis: Dict) -> str:
        """Create implementation strategy section"""
        lines = []
        lines.append("## 🗃️ Strategia di Implementazione")
        
        sprints = plan.get("sprints", [])
        if sprints:
            sprint = sprints[0]
            lines.append(f"**Sprint**: {sprint.get('name', 'Sprint 1')}")
            lines.append(f"**Obiettivo**: {sprint.get('goal', 'Implementazione base')}")
            lines.append(f"**Durata**: {sprint.get('duration', 'TBD')}")
        else:
            lines.append("**Strategia**: Implementazione diretta senza sprint dedicati")
        
        # File structure analysis
        all_paths = self._collect_all_paths(plan)
        if all_paths:
            lines.append(f"**File Interessati**: {len(all_paths)} file")
            lines.append("```")
            for path in sorted(all_paths)[:10]:  # Show first 10
                lines.append(f"  {path}")
            if len(all_paths) > 10:
                lines.append(f"  ... e altri {len(all_paths) - 10} file")
            lines.append("```")
        
        return "\n".join(lines)
    
    def _collect_all_paths(self, plan: Dict) -> List[str]:
        """Collect all unique file paths from tasks"""
        all_paths = []
        for task in plan.get("tasks", []):
            all_paths.extend(task.get("paths", []))
        return list(set(all_paths))
    
    def _create_segmentation_plan(self, plan: Dict) -> str:
        """Create segmentation analysis section"""
        lines = []
        lines.append("## 📊 Piano di Segmentazione")
        
        tasks = plan.get("tasks", [])
        lines.append(f"**Numero di Task**: {len(tasks)}")
        
        # Segmentation rationale based on task count
        if len(tasks) == 1:
            lines.append("**Rationale**: Task singolo, complessità gestibile in un'unica implementazione")
        elif len(tasks) <= 3:
            lines.append("**Rationale**: Segmentazione minima per separare responsabilità logiche")
        elif len(tasks) <= 6:
            lines.append("**Rationale**: Suddivisione moderata per componenti indipendenti")
        else:
            lines.append("**Rationale**: Segmentazione estesa per gestire complessità elevata")
        
        # Priority distribution analysis
        priorities = self._analyze_priority_distribution(tasks)
        if priorities:
            priority_text = ", ".join([f"{count} {priority}" for priority, count in priorities.items()])
            lines.append(f"**Distribuzione Priorità**: {priority_text}")
        
        return "\n".join(lines)
    
    def _analyze_priority_distribution(self, tasks: List[Dict]) -> Dict[str, int]:
        """Analyze task priority distribution"""
        priorities = {}
        for task in tasks:
            priority = task.get("priority", "medium")
            priorities[priority] = priorities.get(priority, 0) + 1
        return priorities
    
    def _create_task_breakdown(self, plan: Dict) -> str:
        """Create detailed task breakdown section"""
        lines = []
        lines.append("## 🔍 Task Breakdown Dettagliato")
        
        tasks = plan.get("tasks", [])
        for i, task in enumerate(tasks, 1):
            lines.extend(self._format_single_task(i, task))
        
        return "\n".join(lines)
    
    def _format_single_task(self, index: int, task: Dict) -> List[str]:
        """Format a single task for detailed breakdown"""
        lines = []
        
        title = task.get("title", f"Task {index}")
        priority = task.get("priority", "medium")
        hours = task.get("estimated_hours", 4)
        depends = task.get("depends_on", [])
        
        lines.append(f"### {index}. {title}")
        lines.append(f"**Priorità**: {priority.upper()} | **Effort**: ~{hours}h")
        
        if depends:
            lines.append(f"**Dipende da**: {', '.join(depends)}")
        
        description = task.get("description", "Nessuna descrizione fornita")
        lines.append(f"**Cosa farà**: {description}")
        
        # Acceptance criteria
        acceptance = task.get("acceptance", [])
        if acceptance:
            lines.append("**Criteri di successo**:")
            for criterion in acceptance:
                lines.append(f"  - {criterion}")
        
        # Deliverables
        paths = task.get("paths", [])
        if paths:
            lines.append("**Deliverable**:")
            for path in paths:
                lines.append(f"  - `{path}`")
        
        lines.append("")  # Empty line between tasks
        return lines
    
    def _create_execution_sequence(self, plan: Dict) -> str:
        """Create execution sequence section"""
        lines = []
        lines.append("## ⚡ Sequenza di Esecuzione")
        lines.append("**Ordine Pianificato**:")
        
        tasks = plan.get("tasks", [])
        for i, task in enumerate(tasks, 1):
            title = task.get("title", f"Task {i}")
            lines.append(f"  {i}. {title}")
            
        # Extra: avvisi su dipendenze sconosciute se presenti nei metadata (quando passati)
        unknown = plan.get("_dependency_warnings") or []
        if unknown:
            lines.append("")
            lines.append("**Avvisi dipendenze sconosciute:**")
            for w in unknown[:10]:
                lines.append(f"- {w}")
        
        return "\n".join(lines)
    
    def _create_risk_analysis(self, plan: Dict, issue_analysis: Dict) -> str:
        """Create risk analysis and mitigation section"""
        lines = []
        lines.append("## ⚠️ Rischi e Mitigazioni")
        
        risks = self._identify_risks(plan, issue_analysis)
        
        if not risks:
            risks.append("🟢 Nessun rischio significativo identificato")
        
        lines.extend(risks)
        return "\n".join(lines)
    
    def _identify_risks(self, plan: Dict, issue_analysis: Dict) -> List[str]:
        """Identify potential risks based on plan and analysis"""
        risks = []
        
        complexity = plan.get("complexity", issue_analysis.get("final_complexity", "medium"))
        tasks = plan.get("tasks", [])
        
        # Complexity-based risks
        if complexity == "high":
            risks.append("🔴 Complessità elevata - Monitoraggio frequente necessario")
        
        # Task count risks
        if len(tasks) > 5:
            risks.append("🟡 Segmentazione estesa - Rischio di dipendenze nascoste")
        
        # Requirements completeness risks
        if not issue_analysis['has_acceptance_criteria']:
            risks.append("🟡 Criteri vaghi - Possibili iterazioni di chiarimento")
        
        # Dependency risks
        has_dependencies = any(task.get("depends_on") for task in tasks)
        if has_dependencies:
            risks.append("🟡 Dipendenze tra task - Sequenza da rispettare rigorosamente")
        
        # Effort estimation risks
        total_hours = sum(task.get("estimated_hours", 4) for task in tasks)
        if total_hours > 40:
            risks.append("🟡 Effort elevato - Possibile sottostima della complessità")
        
        # File scope risks
        all_paths = self._collect_all_paths(plan)
        if len(all_paths) > 20:
            risks.append("🟡 Scope ampio - Molti file da modificare")
        
        return risks
    
    def _create_footer(self) -> str:
        """Create report footer"""
        lines = []
        lines.append("---")
        lines.append("**📅 Next Steps**: L'analyzer procederà con la creazione automatica dei task e l'avvio del primo task in coda.")
        lines.append("**💬 Feedback**: Commenta questo issue per suggerimenti prima dell'esecuzione automatica.")
        
        return "\n".join(lines)
    
    def create_summary_report(self, plan: Dict, issue_analysis: Dict) -> str:
        """Create concise summary report for quick overview"""
        lines = []
        
        # Basic info
        title = issue_analysis.get('title', 'Unknown Issue')
        complexity = plan.get("complexity", "medium")
        task_count = len(plan.get("tasks", []))
        
        lines.append(f"# 📋 Analisi Completata: {title}")
        lines.append(f"**Complessità**: {complexity.upper()}")
        lines.append(f"**Task Creati**: {task_count}")
        
        # Effort summary
        total_hours = sum(task.get("estimated_hours", 4) for task in plan.get("tasks", []))
        lines.append(f"**Effort Totale**: ~{total_hours} ore")
        
        # Policy
        policy = plan.get("policy", "essential-only")
        lines.append(f"**Policy Review**: {policy}")
        
        return "\n".join(lines)