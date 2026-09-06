"""
Generates: Zivaa_Daily_Plan_Documentation.docx
Explains the insights-driven daily plan generation system.

Run: python generate_plan_docs.py
Output: docs/Zivaa_Daily_Plan_Documentation.docx
"""
import os
import sys

user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

doc = Document()

# ── Styles ──
style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(11)

for level in range(1, 4):
    hs = doc.styles[f'Heading {level}']
    hs.font.color.rgb = RGBColor(0x1A, 0x3C, 0x6E)


def add_table(headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
    doc.add_paragraph()


def add_note(text, label="NOTE"):
    p = doc.add_paragraph()
    run = p.add_run(f"{label}: ")
    run.bold = True
    run.font.color.rgb = RGBColor(0x1A, 0x6E, 0x3C)
    p.add_run(text)


# ═══════════════════════════════════════════════════════════════
# TITLE PAGE
# ═══════════════════════════════════════════════════════════════
title = doc.add_heading('Zivaa Eldercare', level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

subtitle = doc.add_heading('Insights-Driven Daily Plan Generation', level=1)
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
meta.add_run('Technical Documentation v1.0\n').bold = True
meta.add_run('June 2026\n\n')
meta.add_run('Confidential — For Internal Use Only')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# TABLE OF CONTENTS
# ═══════════════════════════════════════════════════════════════
doc.add_heading('Table of Contents', level=1)
toc_items = [
    '1. Executive Summary',
    '2. System Architecture & Data Flow',
    '3. Plan Context Builder (build_plan_context)',
    '   3.1 Patient Demographics',
    '   3.2 Today\'s Vitals',
    '   3.3 Insights Engine Integration',
    '   3.4 RCV-Based Lab Trend Alerts',
    '   3.5 Medication Adherence',
    '4. Insights-to-Condition Mapper',
    '5. Composable Fallback Templates',
    '   5.1 Template Design Principles',
    '   5.2 Condition Templates',
    '   5.3 Task Composition & Deduplication',
    '   5.4 Vitals-Based Adjustments',
    '6. LLM Plan Generation (Gemini)',
    '   6.1 Prompt Construction',
    '   6.2 Condition-Specific Instructions',
    '   6.3 Response Format',
    '7. Insights Cache',
    '   7.1 Design',
    '   7.2 Security Compliance',
    '8. API Contract',
    '   8.1 Request Schema',
    '   8.2 Response Schema',
    '   8.3 Backward Compatibility',
    '9. Regional Food System',
    '10. Example: Ranjit Sharma',
    '11. Citation Index',
]
for item in toc_items:
    doc.add_paragraph(item, style='List Number')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 1. EXECUTIVE SUMMARY
# ═══════════════════════════════════════════════════════════════
doc.add_heading('1. Executive Summary', level=1)
doc.add_paragraph(
    'The Zivaa Daily Plan system generates personalised morning-to-night care plans '
    'for elderly patients. Plans include meal suggestions, medication reminders, '
    'activity tasks, and health monitoring checks — all tailored to the individual '
    'patient\'s current health state.'
)
doc.add_paragraph(
    'Version 1.0 of the plan generator used a static prompt with hardcoded patient '
    'data (name, age, baselines) and only distinguished between "diabetes" and '
    '"generic senior" plans.'
)
doc.add_paragraph(
    'The current version (v2.0) is fully insights-driven. It integrates with the '
    'Insights Engine (18 clinical rules), RCV-based lab trend analysis (EFLM '
    'Biological Variation Database), patient demographics, and medication adherence '
    'to produce plans grounded in the patient\'s actual clinical context.'
)

doc.add_heading('Key Metrics', level=2)
add_table(
    ['Metric', 'v1.0 (Old)', 'v2.0 (Current)'],
    [
        ['Conditions handled', '1 (diabetes only)', '8 (composable)'],
        ['Data sources', 'Raw vitals only', 'Vitals + Insights + Labs + Meds'],
        ['Patient identity', 'Hardcoded', 'Dynamic from patients table'],
        ['Lab trends', 'None', 'RCV-filtered from EFLM database'],
        ['Medication awareness', 'None', '7-day adherence rate'],
        ['Caching', 'None', 'In-memory, 1h TTL (Tier 4)'],
        ['Fallback templates', '2 (diabetes/generic)', '8 condition templates, composable'],
        ['Regional foods', '4 regions, 3 items each', '4 regions, 6 items each (incl. condition-specific)'],
    ]
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 2. ARCHITECTURE
# ═══════════════════════════════════════════════════════════════
doc.add_heading('2. System Architecture & Data Flow', level=1)
doc.add_paragraph(
    'The daily plan generation follows a pipeline architecture:'
)

doc.add_heading('Pipeline Steps', level=2)
steps = [
    ('Step 1: Request', 'POST /daily-plan with patient_id (preferred) or raw vitals + conditions (legacy).'),
    ('Step 2: Context Build', 'build_plan_context(patient_id) assembles the full health context by querying '
     'Supabase for patient demographics, today\'s vitals, running the Insights Engine, fetching RCV-based '
     'lab trends, and checking medication adherence.'),
    ('Step 3: Cache Check', 'InsightsCache checks for a valid cached context (1h TTL). On hit, skips '
     'Steps 2a-2e. On miss, executes full pipeline and caches the result.'),
    ('Step 4: Plan Generation', 'The PlanContext is passed to generate_daily_plan() which constructs '
     'an enriched prompt for Gemini. If the LLM is unavailable, the composable fallback system '
     'generates a structured plan from condition templates.'),
    ('Step 5: Response', 'Returns DailyPlanResponse with summary, schedule, optional health_context, '
     'and optional active_alerts.'),
]
for title_text, desc in steps:
    p = doc.add_paragraph()
    run = p.add_run(f'{title_text}: ')
    run.bold = True
    p.add_run(desc)

doc.add_heading('Data Flow Diagram', level=2)
doc.add_paragraph(
    'POST /daily-plan {patient_id}\n'
    '  └→ build_plan_context(patient_id)\n'
    '      ├→ InsightsCache (1h TTL) → [HIT: return cached context]\n'
    '      └→ [MISS]:\n'
    '          ├→ Supabase: patients → name, age, sex, location\n'
    '          ├→ Supabase: conditions → diagnosed conditions\n'
    '          ├→ Supabase: vitals_daily → today\'s vitals\n'
    '          ├→ InsightsEngine.evaluate_patient() → 18 rules → active insights\n'
    '          ├→ get_patient_lab_trends() → RCV-filtered lab alerts\n'
    '          └→ Supabase: medication_logs → 7-day adherence\n'
    '  └→ generate_daily_plan(PlanContext)\n'
    '      ├→ [Gemini available]: enriched prompt → LLM response\n'
    '      └→ [Gemini unavailable]: get_fallback_daily_plan()\n'
    '          ├→ Map insights → condition keys\n'
    '          ├→ Compose condition templates\n'
    '          ├→ Deduplicate tasks\n'
    '          ├→ Apply vitals adjustments\n'
    '          └→ Cap at 4 tasks per slot\n'
    '  └→ DailyPlanResponse {summary, schedule, health_context, active_alerts}'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 3. PLAN CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════
doc.add_heading('3. Plan Context Builder', level=1)
doc.add_paragraph(
    'The build_plan_context(patient_id) function is the bridge between the Insights '
    'Engine and the plan generator. It assembles all health data into a structured '
    'PlanContext dictionary.'
)

doc.add_heading('3.1 Patient Demographics', level=2)
doc.add_paragraph(
    'Fetched from the "patients" Supabase table. Fields used:'
)
add_table(
    ['Field', 'Source Column', 'Usage'],
    [
        ['name', 'full_name', 'Personalised summary and LLM prompt'],
        ['age', 'date_of_birth (computed)', 'Age-appropriate activity levels'],
        ['sex', 'gender', 'Sex-specific thresholds (e.g., anemia)'],
        ['location', 'location_city', 'Regional food recommendations'],
        ['region', 'Derived from location', 'Maps to South/North/East/West food system'],
    ]
)

doc.add_heading('3.2 Today\'s Vitals', level=2)
doc.add_paragraph(
    'Fetched from "vitals_daily" — the most recent row (today or yesterday). '
    'Used in both the LLM prompt and fallback vitals-based adjustments.'
)
add_table(
    ['Vital', 'Source Column', 'Fallback Adjustment Trigger'],
    [
        ['heart_rate', 'avg_heart_rate', 'HR > 85 → add deep breathing'],
        ['bp_systolic', 'bp_systolic', 'SBP > 140 → add deep breathing'],
        ['bp_diastolic', 'bp_diastolic', 'Used in LLM prompt'],
        ['steps', 'total_steps', 'Steps < 1000 → add walking task'],
        ['sleep_hours', 'sleep_hours', 'Sleep < 6h → "keep things gentle"'],
        ['blood_glucose', 'blood_glucose_avg', 'Used in LLM prompt'],
        ['oxygen_sat', 'oxygen_sat_avg', 'Used in LLM prompt'],
        ['body_temp', 'body_temp_avg', 'Used in LLM prompt'],
        ['weight', 'weight_kg', 'Used in LLM prompt'],
        ['mood_score', 'mood_score', 'Used in LLM prompt'],
    ]
)

doc.add_heading('3.3 Insights Engine Integration', level=2)
doc.add_paragraph(
    'The Insights Engine (app/services/insights/engine.py) evaluates 18 clinical rules '
    'across 4 tiers. The plan context extracts Tier 4 (derived) data only — rule IDs, '
    'severity levels, and plain-text messages. No raw Tier 1 PHI is cached.'
)
doc.add_paragraph(
    'Active insights are used in two ways:'
)
p1 = doc.add_paragraph('', style='List Bullet')
p1.add_run('LLM prompt: ').bold = True
p1.add_run('Formatted as "[SEVERITY] Rule Name: message" for the Gemini prompt.')
p2 = doc.add_paragraph('', style='List Bullet')
p2.add_run('Fallback templates: ').bold = True
p2.add_run('Mapped to condition keys via INSIGHT_TO_CONDITION dictionary, then used '
           'to select condition-specific task templates.')

doc.add_heading('3.4 RCV-Based Lab Trend Alerts', level=2)
doc.add_paragraph(
    'Lab trends are fetched from get_patient_lab_trends() which uses the EFLM '
    'Biological Variation Database to compute Reference Change Values (RCV). '
    'Only biomarkers with clinical_flag "worsening" or "needs_attention" are included '
    'in the plan context.'
)
doc.add_paragraph(
    'RCV Formula: RCV = √2 × 1.96 × √(CVi² + CVa²)'
)
doc.add_paragraph(
    'Where CVi = within-individual biological variation and CVa = analytical variation, '
    'both sourced from the EFLM Biological Variation Database (Aarsand et al., 2018).'
)

doc.add_heading('Lab Alert Fields', level=3)
add_table(
    ['Field', 'Description', 'Example'],
    [
        ['biomarker', 'Human-readable biomarker name', 'HbA1c'],
        ['direction', 'Trend direction: rising/declining/stable', 'rising'],
        ['change_pct', 'Percentage change between readings', '+10.3%'],
        ['clinical_flag', 'worsening / needs_attention / stable', 'worsening'],
        ['rate_alert', 'Guideline-specific rate alarm (optional)', 'therapy_review_needed (ADA)'],
    ]
)

doc.add_heading('3.5 Medication Adherence', level=2)
doc.add_paragraph(
    'Fetched from "medication_logs" for the past 7 days. Computed as:'
)
doc.add_paragraph(
    '  adherence_rate = (taken_count / total_scheduled) × 100\n'
    '  missed_count = count of status "missed" or "skipped"'
)
doc.add_paragraph(
    'If adherence_rate < 80%, a prominent medication reminder is added to the '
    'morning slot of both the LLM prompt and the fallback plan.'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 4. INSIGHTS-TO-CONDITION MAPPER
# ═══════════════════════════════════════════════════════════════
doc.add_heading('4. Insights-to-Condition Mapper', level=1)
doc.add_paragraph(
    'Maps active insight rule IDs from the Insights Engine to condition template '
    'keys used by the composable fallback system. This is the bridge between '
    '"what the rules detected" and "what tasks to include in the plan".'
)

add_table(
    ['Insight Rule ID', 'Condition Key', 'Template Actions'],
    [
        ['prediabetes_progression', 'diabetes', 'Glucose checks, low-GI food, foot care'],
        ['glycemic_risk', 'diabetes', 'Glucose checks, low-GI food, foot care'],
        ['kidney_decline', 'ckd', 'Hydration, salt monitoring, BP checks'],
        ['anemia_detection', 'anemia', 'Iron-rich food, rest periods'],
        ['thyroid_dysfunction', 'thyroid', 'Thyroid med timing (30min before food)'],
        ['cardiovascular_risk', 'cardiovascular', 'BP checks, low-sodium dinner, gentle walk'],
        ['hypertension_escalation', 'cardiovascular', 'BP checks, low-sodium dinner, gentle walk'],
        ['respiratory_distress', 'respiratory', 'Breathing exercises, elevated pillow'],
        ['depression_withdrawal', 'mental_health', 'Social connection, hobby time'],
        ['emotional_wellbeing', 'mental_health', 'Social connection, hobby time'],
        ['sleep_disturbance', 'sleep', 'Dim lights, dark bedroom preparation'],
    ]
)

doc.add_paragraph(
    'Additionally, the patient\'s diagnosed conditions from the "conditions" table are '
    'mapped by keyword matching (e.g., "diabetes" in condition name → "diabetes" key). '
    'This ensures conditions are addressed even if the Insights Engine doesn\'t trigger '
    'a specific rule for them on a given day.'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 5. COMPOSABLE FALLBACK TEMPLATES
# ═══════════════════════════════════════════════════════════════
doc.add_heading('5. Composable Fallback Templates', level=1)

doc.add_heading('5.1 Template Design Principles', level=2)
p = doc.add_paragraph()
p.add_run('Clinical grounding: ').bold = True
p.add_run('Each condition template is based on published guidelines referenced in '
          'the corresponding Tier 3 insight rule. For example, the diabetes template '
          'follows ADA 2024 Standards of Care (glucose monitoring, post-meal walks, '
          'diabetic foot checks).')
doc.add_paragraph()
p = doc.add_paragraph()
p.add_run('Composability: ').bold = True
p.add_run('Multiple condition templates merge into a single schedule. A patient with '
          'diabetes + CKD + anemia gets tasks from all three templates without manual '
          'configuration.')
doc.add_paragraph()
p = doc.add_paragraph()
p.add_run('4-word task limit: ').bold = True
p.add_run('All task descriptions are capped at 4 words (excluding the time stamp) '
          'to match mobile UI constraints.')

doc.add_heading('5.2 Condition Templates', level=2)

templates_data = [
    ('Diabetes (ADA 2024)', [
        ['Morning', 'Check blood sugar | 7:30 AM', 'ADA 2024 §6: Self-monitoring'],
        ['Morning', 'Eat [low-GI breakfast] | 8:30 AM', 'Region-specific food'],
        ['Afternoon', 'Post-meal short walk | 1:30 PM', 'ADA 2024 §5: Post-meal activity'],
        ['Evening', 'Check evening glucose | 7:00 PM', 'ADA 2024 §6: Evening monitoring'],
        ['Night', 'Diabetic foot check | 9:30 PM', 'ADA 2024 §12: Foot care'],
    ]),
    ('CKD (KDIGO 2024)', [
        ['Morning', 'Drink warm water | 7:00 AM', 'KDIGO: Hydration management'],
        ['Afternoon', 'Monitor salt intake | 1:00 PM', 'KDIGO: Sodium restriction'],
        ['Evening', 'Check blood pressure | 6:30 PM', 'KDIGO: BP monitoring in CKD'],
        ['Night', 'Track fluid intake | 9:00 PM', 'KDIGO: Fluid balance'],
    ]),
    ('Anemia (WHO 2011)', [
        ['Morning', 'Eat [iron-rich food] | 8:30 AM', 'WHO: Iron supplementation/diet'],
        ['Afternoon', 'Take short rest | 2:30 PM', 'Harrison\'s: Fatigue management'],
    ]),
    ('Thyroid (ATA 2012/2016)', [
        ['Morning', 'Take thyroid medication | 7:00 AM', 'ATA: Levothyroxine on empty stomach'],
        ['Morning', 'Wait before eating | 7:30 AM', 'ATA: 30-60 min fasting after thyroid med'],
    ]),
    ('Cardiovascular (ACC/AHA 2018)', [
        ['Morning', 'Check blood pressure | 8:00 AM', 'ACC/AHA: Home BP monitoring'],
        ['Afternoon', 'Take gentle walk | 2:00 PM', 'ACC/AHA: 150 min/week moderate activity'],
        ['Evening', 'Eat [low-sodium dinner] | 7:30 PM', 'ACC/AHA: DASH diet principles'],
    ]),
    ('Respiratory', [
        ['Morning', 'Do breathing exercises | 8:00 AM', 'BTS: Pulmonary rehabilitation'],
        ['Night', 'Elevate head pillow | 9:30 PM', 'BTS: Orthopnea management'],
    ]),
    ('Mental Health (DSM-5/PHQ-2)', [
        ['Afternoon', 'Call friend or family | 3:00 PM', 'APA: Social engagement for depression'],
        ['Evening', 'Enjoy calm hobby | 7:00 PM', 'APA: Behavioural activation'],
    ]),
    ('Sleep (AASM/ICSD-3)', [
        ['Evening', 'Dim lights early | 8:00 PM', 'AASM: Light hygiene'],
        ['Night', 'Prepare dark bedroom | 9:30 PM', 'AASM: Sleep environment optimisation'],
    ]),
]

for template_name, tasks in templates_data:
    doc.add_heading(template_name, level=3)
    add_table(
        ['Time Slot', 'Task', 'Clinical Basis'],
        tasks
    )

doc.add_heading('5.3 Task Composition & Deduplication', level=2)
doc.add_paragraph(
    'When multiple conditions are active, their templates are merged into a unified schedule. '
    'The deduplication system prevents duplicate tasks using two mechanisms:'
)
p1 = doc.add_paragraph('', style='List Bullet')
p1.add_run('Exact dedup: ').bold = True
p1.add_run('Tasks with the same text (before the "|" time separator) are deduplicated globally.')
p2 = doc.add_paragraph('', style='List Bullet')
p2.add_run('Meal dedup: ').bold = True
p2.add_run('All "Eat ..." tasks in the same time slot are treated as the same category. '
           'If a slot already has a meal task (e.g., "Eat Methi Poha" from the base schedule), '
           'a condition-specific meal (e.g., "Eat Iron-Rich Breakfast") for the same slot is skipped. '
           'This prevents duplicate dinner entries when multiple conditions suggest different foods.')

doc.add_heading('5.4 Vitals-Based Adjustments', level=2)
doc.add_paragraph(
    'After condition templates are composed, additional tasks are injected based on '
    'today\'s vitals:'
)
add_table(
    ['Condition', 'Threshold', 'Task Added'],
    [
        ['Low activity', 'Steps < 1000 AND BP ≤ 150 AND HR ≤ 90', 'Walk around house | 4:00 PM'],
        ['Elevated BP/HR', 'SBP > 140 OR HR > 85', 'Do deep breathing | 8:00 PM'],
        ['Low med adherence', 'Adherence rate < 80%', 'Set medication reminder | 9:00 AM (inserted first)'],
        ['Poor sleep', 'Sleep < 6 hours', 'Summary note: "keep things gentle"'],
    ]
)

doc.add_paragraph(
    'Each time slot is capped at 4 tasks maximum. Tasks from condition templates '
    'are prioritised over vitals-based adjustments (which are appended last).'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 6. LLM PLAN GENERATION
# ═══════════════════════════════════════════════════════════════
doc.add_heading('6. LLM Plan Generation (Gemini)', level=1)

doc.add_heading('6.1 Prompt Construction', level=2)
doc.add_paragraph(
    'When Gemini is available, the PlanContext is used to construct an enriched prompt '
    'that includes all health context. The prompt has the following sections:'
)
add_table(
    ['Section', 'Content Source', 'Purpose'],
    [
        ['PATIENT', 'patients table', 'Name, age, sex — personalised addressing'],
        ['LOCATION', 'patients.location_city', 'Region-appropriate food suggestions'],
        ['CONDITIONS', 'conditions table', 'Disease context for the LLM'],
        ['TODAY\'S VITALS', 'vitals_daily (latest)', 'Current state: HR, BP, sleep, steps, glucose'],
        ['ACTIVE HEALTH ALERTS', 'InsightsEngine output', 'Formatted as [SEVERITY] Rule: message'],
        ['LAB TRENDS', 'RCV-filtered lab alerts', 'Worsening biomarkers + rate alerts'],
        ['MEDICATION STATUS', 'medication_logs (7d)', 'Adherence rate + missed count'],
        ['CONDITION INSTRUCTIONS', 'INSIGHT_TO_CONDITION map', 'Specific task guidance per condition'],
    ]
)

doc.add_heading('6.2 Condition-Specific Instructions', level=2)
doc.add_paragraph(
    'Based on the active conditions detected from insights, the prompt includes '
    'specific instructions for the LLM:'
)
add_table(
    ['Condition', 'LLM Instruction'],
    [
        ['diabetes', 'Include glucose monitoring tasks and carbohydrate-controlled meals'],
        ['ckd', 'Include hydration reminders, salt monitoring, and BP checks'],
        ['anemia', 'Include iron-rich food suggestions and rest periods'],
        ['thyroid', 'Include thyroid medication timing (30 min before breakfast)'],
        ['cardiovascular', 'Include BP checks, low-sodium meals, and gentle cardiac exercise'],
    ]
)

doc.add_heading('6.3 Response Format', level=2)
doc.add_paragraph(
    'The LLM is instructed to return exact JSON with responseMimeType: "application/json". '
    'The system appends health_context and active_alerts to the LLM response for transparency.'
)
doc.add_paragraph(
    'General instructions enforced in the prompt:'
)
for instruction in [
    'Warm, comforting tone — like a reassuring family nurse',
    'No medical jargon, no graphs or charts',
    '2-4 tasks per time period (morning, afternoon, evening, night)',
    'Each task MUST be 4 words maximum (excluding time stamp)',
    'Food items MUST be specific, healthy Indian recipes for the patient\'s region',
    'The plan MUST address the active health alerts',
]:
    doc.add_paragraph(instruction, style='List Bullet')

doc.add_paragraph(
    'Model: Gemini 2.5 Flash via generativelanguage.googleapis.com. '
    'Timeout: 20 seconds. On failure: falls back to composable templates.'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 7. INSIGHTS CACHE
# ═══════════════════════════════════════════════════════════════
doc.add_heading('7. Insights Cache', level=1)

doc.add_heading('7.1 Design', level=2)
add_table(
    ['Property', 'Value'],
    [
        ['Type', 'In-memory Python dictionary (process-local)'],
        ['Key', 'patient_id (UUID string)'],
        ['Value', 'PlanContext dict (Tier 4 derived data only)'],
        ['TTL', '3600 seconds (1 hour)'],
        ['Eviction', 'Lazy — checked on get(), expired entries deleted'],
        ['Invalidation', 'Manual via invalidate(patient_id) or clear()'],
        ['Persistence', 'None — cache is lost on server restart'],
    ]
)

doc.add_heading('7.2 Security Compliance', level=2)
doc.add_paragraph(
    'The cache design was validated against the Zivaa Security & Compliance Blueprint:'
)
add_table(
    ['Blueprint Section', 'Requirement', 'Compliance'],
    [
        ['§1 Data Classification', 'Tier 1 PHI must be encrypted at rest', 'Cache stores Tier 4 (derived) data only — rule IDs, severity, messages. No raw lab values or vitals.'],
        ['§2 RLS', 'Patient-scoped access', 'Cache keyed by patient_id, accessed only by service_role backend.'],
        ['§3c Field Encryption', 'Sensitive fields encrypted', 'No raw PHI in cache. Insight messages are plain-text summaries.'],
        ['§6 Audit Logging', 'Access to sensitive data logged', 'No new external access surface. Cache is internal.'],
        ['§9 Data Retention', 'Retention limits enforced', '1h auto-eviction. No persistence to disk.'],
    ]
)

add_note(
    'The cache contains only Tier 4 System/Derived data as classified in the '
    'security blueprint. Raw Tier 1 PHI (lab values, BP readings, heart rate readings) '
    'are fetched fresh from Supabase on each cache miss and are NOT stored in the cache.',
    label='SECURITY'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 8. API CONTRACT
# ═══════════════════════════════════════════════════════════════
doc.add_heading('8. API Contract', level=1)

doc.add_heading('8.1 Request Schema', level=2)
doc.add_paragraph('POST /api/v1/health/daily-plan')
add_table(
    ['Field', 'Type', 'Required', 'Description'],
    [
        ['patient_id', 'string (UUID)', 'Recommended', 'Patient ID for full insights-driven plan generation'],
        ['vitals', 'Dict[str, float]', 'If no patient_id', 'Raw vital readings (legacy mode)'],
        ['conditions', 'List[str]', 'No', 'Active chronic conditions (legacy mode)'],
        ['location', 'string', 'No', 'Location for food customisation (legacy mode)'],
    ]
)

doc.add_heading('8.2 Response Schema', level=2)
add_table(
    ['Field', 'Type', 'Always Present', 'Description'],
    [
        ['summary', 'string', 'Yes', 'Warm, empathetic daily overview'],
        ['schedule', 'DailyPlanSchedule', 'Yes', 'Object with morning/afternoon/evening/night task arrays'],
        ['schedule.*.task', 'string', 'Yes', 'Task description (max 4 words + optional time)'],
        ['schedule.*.completed', 'boolean', 'Yes', 'Always false initially'],
        ['health_context', 'Dict', 'Optional', 'Conditions addressed, alert counts, med adherence rate'],
        ['active_alerts', 'List[str]', 'Optional', 'Names of top 5 active health alerts addressed'],
    ]
)

doc.add_heading('8.3 Backward Compatibility', level=2)
doc.add_paragraph(
    'The API maintains backward compatibility through generate_daily_plan_legacy(). '
    'Existing clients that send {vitals, conditions, location} without a patient_id '
    'will still receive a valid plan — generated without insights/lab/med context.'
)
add_table(
    ['Request Type', 'Flow', 'Insights?', 'Labs?', 'Meds?'],
    [
        ['{patient_id}', 'Full insights-driven', 'Yes (18 rules)', 'Yes (RCV-filtered)', 'Yes (7-day)'],
        ['{vitals, conditions}', 'Legacy fallback', 'No', 'No', 'No'],
        ['{patient_id, vitals}', 'Full insights-driven (vitals from context override)', 'Yes', 'Yes', 'Yes'],
    ]
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 9. REGIONAL FOOD SYSTEM
# ═══════════════════════════════════════════════════════════════
doc.add_heading('9. Regional Food System', level=1)
doc.add_paragraph(
    'Food suggestions are region-appropriate Indian cuisine, mapped from the patient\'s '
    'location_city to one of four dietary regions. Each region has standard meal items '
    'plus condition-specific alternatives.'
)

doc.add_heading('Region Detection', level=2)
doc.add_paragraph(
    'The get_region_from_location() function maps city/state names to regions via '
    'keyword matching:'
)
add_table(
    ['Region', 'Cities/States Matched'],
    [
        ['South', 'Bangalore, Chennai, Hyderabad, Kochi, Kerala, Karnataka, Tamil Nadu, Andhra, Telangana, Mysore, Coimbatore'],
        ['West', 'Mumbai, Pune, Ahmedabad, Surat, Gujarat, Maharashtra, Goa, Nagpur, Rajkot'],
        ['East', 'Kolkata, Bengal, Odisha, Bhubaneswar, Assam, Guwahati, Patna, Bihar, Ranchi'],
        ['North', 'Default for all other locations including Delhi, UP, Rajasthan, Punjab, etc.'],
    ]
)

doc.add_heading('Food Items by Region', level=2)
add_table(
    ['Meal Type', 'South', 'North', 'West', 'East'],
    [
        ['Breakfast', 'Oats Idli', 'Missi Roti', 'Methi Poha', 'Suji Upma'],
        ['Lunch', 'Sambhar Rice', 'Roti Sabzi', 'Bajra Roti', 'Palak Dal'],
        ['Dinner', 'Ragi Dosa', 'Moong Dal', 'Kadhi Khichdi', 'Sattu Paratha'],
        ['Iron-rich (Anemia)', 'Ragi Idli', 'Bajra Roti', 'Nachni Roti', 'Sattu Drink'],
        ['Low-sodium (CVD)', 'Steamed Idli', 'Dal Chawal', 'Plain Khichdi', 'Moong Khichdi'],
        ['Low-GI (Diabetes)', 'Oats Upma', 'Besan Chilla', 'Sprouts Poha', 'Chana Sattu'],
    ]
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 10. EXAMPLE: RANJIT SHARMA
# ═══════════════════════════════════════════════════════════════
doc.add_heading('10. Example: Ranjit Sharma', level=1)
doc.add_paragraph(
    'The following shows a real plan generated for patient Ranjit Sharma using the '
    'insights-driven system.'
)

doc.add_heading('Patient Profile', level=2)
add_table(
    ['Field', 'Value'],
    [
        ['Name', 'Ranjit Sharma'],
        ['Age', '72 years'],
        ['Sex', 'Male'],
        ['Location', 'Pune (West India)'],
        ['Conditions', 'Type 2 Diabetes, Essential Hypertension, Mild CKD Stage 2, Dyslipidemia'],
    ]
)

doc.add_heading('Health Context (Day of Test)', level=2)
add_table(
    ['Metric', 'Value', 'Clinical Significance'],
    [
        ['Heart Rate', '91 bpm', 'Elevated (tachycardia range)'],
        ['Blood Pressure', '155/83 mmHg', 'Stage 2 Hypertension (ACC/AHA)'],
        ['Steps', '262', 'Very low activity (goal: 1500)'],
        ['Sleep', '4.7 hours', 'Severely short (baseline ~7h)'],
        ['Blood Glucose', '155 mg/dL', 'Elevated'],
        ['SpO2', '93%', 'Below normal (threshold: 94%)'],
        ['Body Temp', '37.8°C', 'Low-grade fever'],
        ['Mood Score', '2/5', 'Low mood'],
        ['Med Adherence', '72.2%', 'Below 80% threshold'],
    ]
)

doc.add_heading('Active Insights (11 triggered)', level=2)
add_table(
    ['Severity', 'Insight', 'Condition Mapped'],
    [
        ['HIGH', 'Functional Decline / Fall Risk', '—'],
        ['HIGH', 'Acute Illness Onset', '—'],
        ['HIGH', 'Fever / Infection Detection', '—'],
        ['HIGH', 'Depression / Social Withdrawal Risk', 'mental_health'],
        ['HIGH', 'Kidney Function Decline', 'ckd'],
        ['MEDIUM', 'Respiratory Distress Warning', 'respiratory'],
        ['MEDIUM', 'Emotional Wellbeing Decline', 'mental_health'],
        ['MEDIUM', 'Pre-Diabetes → Diabetes Progression', 'diabetes'],
        ['MEDIUM', 'Anemia / Low Iron Detection', 'anemia'],
        ['MEDIUM', 'Thyroid Dysfunction', 'thyroid'],
        ['LOW', 'Chronic Sleep Disturbance', 'sleep'],
    ]
)

doc.add_heading('Key Lab Alerts', level=2)
add_table(
    ['Biomarker', 'Direction', 'Change', 'Rate Alert'],
    [
        ['HbA1c', 'Rising', '+10.3%', 'therapy_review_needed (ADA)'],
        ['eGFR', 'Declining', '-25.6%', 'rapid_progression (KDIGO)'],
        ['Hemoglobin', 'Declining', '-15.2%', '—'],
        ['TSH', 'Rising', '+75.0%', '—'],
        ['CRP', 'Rising', '+244.4%', '—'],
        ['Ferritin', 'Declining', '-44.4%', '—'],
    ]
)

doc.add_heading('Generated Plan (Gemini LLM)', level=2)
doc.add_paragraph(
    'Summary: "Good morning, dear Ranjit! I\'m here to help us gently navigate today. '
    'We\'ve noticed your energy is a bit low, and some changes in your heart rate, blood '
    'pressure, and sugar levels. We\'ll focus on getting you plenty of rest, some gentle '
    'movement, and delicious, nourishing meals to support your body and lift your spirits."'
)

add_table(
    ['Time', 'Tasks', 'Conditions Addressed'],
    [
        ['Morning', 'Thyroid medicine (7:00 AM)\nCheck blood sugar (7:25 AM)\nPoha, morning medicines (7:30 AM)\nGentle chair stretches (8:30 AM)',
         'Thyroid, Diabetes, General wellness'],
        ['Afternoon', 'Hydrate, low salt (12:00 PM)\nCheck blood pressure (12:30 PM)\nDal khichdi, afternoon meds (1:00 PM)\nRelax, gentle rest (2:00 PM)',
         'CKD, Cardiovascular, Anemia'],
        ['Evening', 'Check blood sugar (6:30 PM)\nShort walk indoors (6:45 PM)\nBesan cheela, evening meds (7:30 PM)\nSip warm water (8:30 PM)',
         'Diabetes, Activity, Hydration'],
        ['Night', 'Check blood pressure (9:00 PM)\nPrepare for sleep (9:30 PM)\nNo screens now (9:45 PM)\nRest well, Ranjit (10:00 PM)',
         'Cardiovascular, Sleep'],
    ]
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# 11. CITATION INDEX
# ═══════════════════════════════════════════════════════════════
doc.add_heading('11. Citation Index', level=1)

citations = [
    'ADA. "Standards of Care in Diabetes — 2024." Diabetes Care. 2024;47(Suppl 1). §2, §3, §5, §6, §12.',
    'Aarsand AK, Fernandez-Calle P, et al. "The EuBIVAS: Within- and Between-Subject Biological Variation Data." Clin Chem. 2018;64(9):1380-1393.',
    'Fraser CG. "Biological Variation: From Principles to Practice." AACC Press, 2001.',
    'Fraser CG. "Reference change values." Clin Chem Lab Med. 2012;50(5):807-812.',
    'Garber JR, et al. "Clinical Practice Guidelines for Hypothyroidism." ATA/AACE 2012. Thyroid. 2012;22(12):1200-1235.',
    'Grundy SM, et al. "2018 AHA/ACC Guideline on Blood Cholesterol." J Am Coll Cardiol. 2019;73(24):e285-e350.',
    'KDIGO 2024. "Clinical Practice Guideline for CKD." Kidney Int Suppl. 2024;14(4S):e1-e314.',
    'Kroenke K, et al. "The PHQ-2." Med Care. 2003;41(11):1284-1292.',
    'O\'Driscoll BR, et al. "BTS Guideline for Oxygen Use." Thorax. 2017;72(Suppl 1):ii1-ii90.',
    'Ricos C, et al. "Current databases on biological variation." Scand J Clin Lab Invest. 1999;59(7):491-500.',
    'Ross DS, et al. "2016 ATA Guidelines for Hyperthyroidism." Thyroid. 2016;26(10):1343-1421.',
    'Whelton PK, et al. "2017 ACC/AHA Guideline for High Blood Pressure." Hypertension. 2018;71(6):e13-e115.',
    'WHO. "Haemoglobin concentrations for the diagnosis of anaemia." 2011. WHO/NMH/NHD/MNM/11.1.',
    'EFLM Biological Variation Database. https://biologicalvariation.eu/ (Accessed June 2026).',
    'Zivaa Security & Compliance Blueprint v1.0. Internal document, June 2026.',
]

for i, c in enumerate(citations, 1):
    doc.add_paragraph(f'{i}. {c}', style='List Number')

# ═══════════════════════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════════════════════
output_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'docs', 'Zivaa_Daily_Plan_Documentation.docx'
)
os.makedirs(os.path.dirname(output_path), exist_ok=True)
doc.save(output_path)
print(f"Document saved to: {output_path}")
