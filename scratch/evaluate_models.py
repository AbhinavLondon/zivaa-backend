import sys
import os
import asyncio
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.services.insights.data_fetcher import fetch_patient_context
from app.services.insights.engine import engine
from app.services.llm_nudge import generate_clinical_nudge
from app.services.llm_plan import build_plan_context, generate_daily_plan
from app.services.daily_summary import generate_daily_summary

from app.services.medgemma_services import (
    generate_medgemma_alerts,
    generate_medgemma_nudge,
    generate_medgemma_plan,
    generate_medgemma_summary
)

async def evaluate_patient(pid: str, name: str) -> str:
    print(f"Running evaluation for {name} ({pid})...")
    
    # 1. Fetch Shared Patient Context
    ctx = fetch_patient_context(pid)
    
    # 2. Rules engine output
    rules_output = engine.evaluate_patient(pid, ctx)
    rules_alerts = []
    for insight in rules_output.active_insights:
        rules_alerts.append({
            "name": insight.name,
            "severity": insight.severity.value,
            "category": insight.category.value,
            "message": insight.message,
            "evidence": insight.evidence
        })
        
    # 3. MedGemma raw alerts
    print(f"  - Running MedGemma Diagnostics Alerts...")
    medgemma_alerts = await generate_medgemma_alerts(ctx)
    
    # 4. Plan Context
    plan_ctx = build_plan_context(pid)
    
    # 5. Run standard generations
    print(f"  - Running Gemini Nudge, Plan, Summary...")
    gemini_nudge = await generate_clinical_nudge(rules_output.active_insights, patient_name=name)
    gemini_plan = await generate_daily_plan(plan_ctx)
    gemini_summary = await generate_daily_summary(pid, patient_name=name)
    
    # 6. Run MedGemma generations
    print(f"  - Running MedGemma Nudge, Plan, Summary...")
    medgemma_nudge = await generate_medgemma_nudge(rules_output.active_insights, patient_name=name)
    medgemma_plan = await generate_medgemma_plan(plan_ctx)
    medgemma_summary = await generate_medgemma_summary(pid, patient_name=name)
    
    # 7. Generate comparison markdown segment
    md = []
    md.append(f"## Patient: {name} ({pid[:8]}...)")
    md.append("")
    
    # Section A: Alerts
    md.append("### 1. Active Alerts / Diagnostics")
    md.append("| Rules Engine (Deterministic) | MedGemma Diagnostics (Raw Reasoner) |")
    md.append("| :--- | :--- |")
    
    # Pair them up
    max_alerts = max(len(rules_alerts), len(medgemma_alerts))
    for i in range(max_alerts):
        rules_col = ""
        medgemma_col = ""
        if i < len(rules_alerts):
            a = rules_alerts[i]
            rules_col = f"**[{a['severity']}] {a['name']}**<br>{a['message']}<br>*Evidence: {a['evidence']}*"
        if i < len(medgemma_alerts):
            a = medgemma_alerts[i]
            medgemma_col = f"**[{a.get('severity')}] {a.get('name')}**<br>{a.get('message')}<br>*Evidence: {a.get('evidence')}*"
        md.append(f"| {rules_col} | {medgemma_col} |")
    if max_alerts == 0:
        md.append("| No concerns triggered. | No concerns triggered. |")
    md.append("")
    
    # Section B: Caregiver Nudges
    md.append("### 2. Caregiver Nudges")
    md.append("| Gemini 3.5 Flash | MedGemma (Vertex AI) |")
    md.append("| :--- | :--- |")
    md.append(
        f"| **Title:** {gemini_nudge.get('nudge_title')}<br>"
        f"**Risk:** {gemini_nudge.get('risk_level')}<br>"
        f"**Text:** {gemini_nudge.get('nudge_text')}<br>"
        f"**Why:** {gemini_nudge.get('why_flagged')}<br>"
        f"**Steps:** {gemini_nudge.get('action_steps')} | "
        f"**Title:** {medgemma_nudge.get('nudge_title')}<br>"
        f"**Risk:** {medgemma_nudge.get('risk_level')}<br>"
        f"**Text:** {medgemma_nudge.get('nudge_text')}<br>"
        f"**Why:** {medgemma_nudge.get('why_flagged')}<br>"
        f"**Steps:** {medgemma_nudge.get('action_steps')} |"
    )
    md.append("")
    
    # Section C: Daily Summaries
    md.append("### 3. Senior Morning Summaries (2-sentence Brief)")
    md.append("| Gemini 3.5 Flash | MedGemma (Vertex AI) |")
    md.append("| :--- | :--- |")
    md.append(f"| {gemini_summary.get('summary')} | {medgemma_summary.get('summary')} |")
    md.append("")
    
    # Section D: Daily Care Plans
    md.append("### 4. Daily Care Plans (Schedule)")
    md.append("| Gemini 3.5 Flash | MedGemma (Vertex AI) |")
    md.append("| :--- | :--- |")
    
    g_schedule = gemini_plan.get("schedule", {})
    m_schedule = medgemma_plan.get("schedule", {})
    
    # Show side-by-side tasks for each time period
    periods = ["morning", "afternoon", "evening", "night"]
    for p in periods:
        g_tasks = g_schedule.get(p, [])
        m_tasks = m_schedule.get(p, [])
        g_tasks_str = "<br>".join([f"- {t.get('task')}" for t in g_tasks]) or "None"
        m_tasks_str = "<br>".join([f"- {t.get('task')}" for t in m_tasks]) or "None"
        md.append(f"| **{p.upper()}**:<br>{g_tasks_str} | **{p.upper()}**:<br>{m_tasks_str} |")
    md.append("")
    md.append("---")
    md.append("")
    
    return "\n".join(md)

async def main():
    print("Starting MedGemma vs Gemini Side-by-Side Evaluation...")
    report_title = "# MedGemma vs Gemini Side-by-Side Evaluation Report\n\n"
    report_desc = f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nThis report compares the outputs of the standard Zivaa implementation (powered by Python rules and Gemini Flash) with the experimental MedGemma/Gemini Pro clinical reasoning pipeline.\n\n"
    
    patients = [
        ("11111111-1111-1111-1111-111111111111", "Ranjit"),
        ("33333333-3333-3333-3333-333333333333", "Shashank"),
        ("22222222-2222-2222-2222-222222222222", "Neha")
    ]
    
    sections = []
    for pid, name in patients:
        try:
            sec = await evaluate_patient(pid, name)
            sections.append(sec)
        except Exception as e:
            print(f"Failed to evaluate {name}: {e}")
            sections.append(f"## Patient: {name}\n\nFailed to evaluate: {e}\n\n---")
            
    full_report = report_title + report_desc + "\n".join(sections)
    
    # Save to artifacts directory
    artifact_dir = r"C:\Users\abhin\.gemini\antigravity-ide\brain\abe0d3c8-a8dd-4d90-b77a-cfd630dcc462"
    report_path = os.path.join(artifact_dir, "medgemma_comparison_report.md")
    
    # Ensure directory exists
    os.makedirs(artifact_dir, exist_ok=True)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(full_report)
        
    print(f"Evaluation report written successfully to: {report_path}")

if __name__ == "__main__":
    asyncio.run(main())
