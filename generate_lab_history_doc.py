"""
Generates a professional Word document explaining the Lab History &
Biomarker Trend Analysis module for Zivaa.
"""

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import os

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "Lab_History_Technical_Document.docx")


def set_cell_shading(cell, color_hex):
    """Apply background shading to a table cell."""
    shading = cell._element.get_or_add_tcPr()
    shd = shading.makeelement(qn('w:shd'), {
        qn('w:fill'): color_hex,
        qn('w:val'): 'clear',
    })
    shading.append(shd)


def add_styled_table(doc, headers, rows, col_widths=None):
    """Add a formatted table to the document."""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = header
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(9)

    # Data rows
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)

    return table


def build_document():
    doc = Document()

    # -- Document styles --
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)

    # ================================================================
    # TITLE PAGE
    # ================================================================
    doc.add_paragraph()
    doc.add_paragraph()
    title = doc.add_heading('Lab History & Biomarker\nTrend Analysis', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph('Technical Documentation')
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.runs[0].font.size = Pt(16)
    subtitle.runs[0].font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    doc.add_paragraph()
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run('Zivaa Health Platform\n').font.size = Pt(12)
    meta.add_run('Backend Service: ').font.size = Pt(10)
    run = meta.add_run('app/services/lab_history.py')
    run.font.size = Pt(10)
    run.italic = True
    meta.add_run('\n\nJune 2026').font.size = Pt(10)

    doc.add_page_break()

    # ================================================================
    # TABLE OF CONTENTS (manual)
    # ================================================================
    doc.add_heading('Table of Contents', level=1)
    toc_items = [
        '1. Overview',
        '2. Architecture',
        '3. API Endpoints',
        '4. Raw Lab History (get_patient_lab_history)',
        '5. Biomarker Trend Analysis (get_patient_lab_trends)',
        '   5.1 Reference Change Value (RCV)',
        '   5.2 EFLM Biological Variation Database',
        '   5.3 Two-Tier Trend Direction Algorithm',
        '   5.4 Zone Classification',
        '   5.5 Clinical Flag Decision Matrix',
        '   5.6 Inverse-Polarity Biomarkers',
        '   5.7 Rate-of-Change Alerts',
        '6. Example Output (Ranjit\'s Lab Data)',
        '7. Evidence Strength Assessment',
        '8. Citations & References',
    ]
    for item in toc_items:
        p = doc.add_paragraph(item)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(0)

    doc.add_page_break()

    # ================================================================
    # 1. OVERVIEW
    # ================================================================
    doc.add_heading('1. Overview', level=1)

    doc.add_paragraph(
        'The Lab History module provides two core capabilities for the '
        'Zivaa health platform:'
    )

    doc.add_paragraph(
        'Raw Lab History: Fetches all historical lab results for a patient '
        'from Supabase, groups them by biomarker code, and returns '
        'chronologically sorted readings with reference ranges. This powers '
        'frontend tables and charts.',
        style='List Bullet'
    )
    doc.add_paragraph(
        'Biomarker Trend Analysis: Computes per-biomarker trend direction, '
        'rate of change, zone classification, and clinical interpretation. '
        'Uses published biological variation data (EFLM database) to '
        'distinguish real clinical trends from normal biological noise.',
        style='List Bullet'
    )

    doc.add_paragraph(
        'The module is designed for a caregiver-facing application where '
        'family members monitor elderly patients\' lab results over time. '
        'The trend analysis answers the core question: "Is this biomarker '
        'getting better, worse, or staying the same?"'
    )

    # ================================================================
    # 2. ARCHITECTURE
    # ================================================================
    doc.add_heading('2. Architecture', level=1)

    doc.add_paragraph(
        'The module follows a layered architecture:'
    )

    add_styled_table(doc,
        ['Layer', 'Component', 'Responsibility'],
        [
            ['Data', 'Supabase (lab_results table)', 'Stores raw lab readings with biomarker codes, values, units, reference ranges, and flags'],
            ['Service', 'get_patient_lab_history()', 'Pure data retrieval -- fetches and groups lab results by biomarker'],
            ['Service', 'get_patient_lab_trends()', 'Trend computation -- calls lab_history internally, then computes direction, rate, zone, and clinical flag'],
            ['API', 'GET /lab-history/{patient_id}', 'Exposes raw history for frontend tables/charts'],
            ['API', 'GET /lab-trends/{patient_id}', 'Exposes computed trend analysis with RCV thresholds'],
        ],
        col_widths=[2.5, 5.0, 8.5]
    )

    doc.add_paragraph()
    doc.add_paragraph(
        'Key design decision: get_patient_lab_trends() internally calls '
        'get_patient_lab_history() rather than querying Supabase directly. '
        'This avoids duplicating the database query logic and ensures '
        'consistency between the raw data and the trend computation.'
    )

    # ================================================================
    # 3. API ENDPOINTS
    # ================================================================
    doc.add_heading('3. API Endpoints', level=1)

    doc.add_heading('GET /api/v1/health/lab-history/{patient_id}', level=2)
    doc.add_paragraph(
        'Returns raw chronological lab data grouped by biomarker. '
        'Supports optional filtering via ?biomarker=HBA1C&biomarker=FBS. '
        'The available_biomarkers list is always unfiltered (for UI dropdowns).'
    )

    doc.add_heading('GET /api/v1/health/lab-trends/{patient_id}', level=2)
    doc.add_paragraph(
        'Returns computed trend analysis per biomarker. Each entry includes: '
        'trend_direction, change_absolute, change_percent, rate_per_month, '
        'zone, clinical_flag, rcv_threshold_pct, and optionally rate_alert. '
        'Supports the same ?biomarker= filtering.'
    )

    # ================================================================
    # 4. RAW LAB HISTORY
    # ================================================================
    doc.add_heading('4. Raw Lab History', level=1)

    doc.add_paragraph(
        'The get_patient_lab_history() function is a pure data-retrieval '
        'function with no trend computation. It:'
    )

    steps = [
        'Queries the lab_results table in Supabase for all records matching the patient_id, ordered by measured_at ascending.',
        'Joins to the lab_reports table to pull report_name and lab_name for each reading.',
        'Extracts all unique biomarker codes into an available_biomarkers list (always unfiltered, for frontend dropdown menus).',
        'Groups readings by biomarker_code into comparison_data, applying the optional biomarker_codes filter.',
        'Each biomarker group includes: code, name, unit, reference_low, reference_high, category, and a chronological history array.',
    ]
    for step in steps:
        doc.add_paragraph(step, style='List Number')

    doc.add_paragraph(
        'The reference_low and reference_high values come directly from '
        'the lab reports stored in Supabase. These are set by the clinical '
        'laboratory that performed the test, following CLSI EP28-A3c guidelines '
        '(central 95% interval of a healthy reference population).'
    )

    # ================================================================
    # 5. BIOMARKER TREND ANALYSIS
    # ================================================================
    doc.add_heading('5. Biomarker Trend Analysis', level=1)

    doc.add_paragraph(
        'The trend analysis layer computes five fields per biomarker:'
    )

    add_styled_table(doc,
        ['Field', 'Type', 'Description'],
        [
            ['trend_direction', 'string', 'rising | declining | stable | fluctuating | insufficient_data'],
            ['change_absolute', 'float', 'Latest value minus first value'],
            ['change_percent', 'float', 'Percentage change from first to latest reading'],
            ['rate_per_month', 'float', 'Absolute change divided by elapsed months'],
            ['zone', 'string', 'Where the latest value sits vs. the reference range'],
            ['clinical_flag', 'string', 'improving | worsening | stable | needs_attention'],
            ['rcv_threshold_pct', 'float', 'The RCV percentage applied (for auditability)'],
            ['rate_alert', 'object?', 'Present only if rate exceeds a published clinical threshold'],
        ],
        col_widths=[3.5, 2.0, 10.5]
    )

    # 5.1 RCV
    doc.add_heading('5.1 Reference Change Value (RCV)', level=2)

    doc.add_paragraph(
        'The central clinical question in trend analysis is: "Is the '
        'difference between two lab readings a real change, or just normal '
        'biological and analytical noise?"'
    )

    doc.add_paragraph(
        'The Reference Change Value (RCV) answers this question. It is the '
        'minimum percentage change between two consecutive readings that is '
        'statistically significant at the 95% confidence level, accounting '
        'for both analytical imprecision and within-subject biological variation.'
    )

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('RCV = \u221a2 \u00d7 Z \u00d7 \u221a(CVa\u00b2 + CVi\u00b2)')
    run.bold = True
    run.font.size = Pt(13)

    doc.add_paragraph()
    doc.add_paragraph('CVi = within-subject biological coefficient of variation (%)', style='List Bullet')
    doc.add_paragraph('CVa = analytical coefficient of variation (%)', style='List Bullet')
    doc.add_paragraph('Z = 1.96 for 95% bidirectional confidence (recommended by Fraser 2001)', style='List Bullet')

    doc.add_paragraph(
        'Example: For HbA1c (CVi=1.9%, CVa=1.5%), RCV = \u221a2 \u00d7 1.96 \u00d7 '
        '\u221a(1.5\u00b2 + 1.9\u00b2) = 6.7%. This means a change of less than 6.7% '
        'between two HbA1c readings cannot be distinguished from normal '
        'biological fluctuation.'
    )

    # 5.2 EFLM Database
    doc.add_heading('5.2 EFLM Biological Variation Database', level=2)

    doc.add_paragraph(
        'The CVi and CVa values are sourced from the EFLM (European '
        'Federation of Clinical Chemistry and Laboratory Medicine) '
        'Biological Variation Database (https://biologicalvariation.eu/), '
        'with primary sources from Aarsand et al. 2018 and Ricos et al. 1999.'
    )

    add_styled_table(doc,
        ['Biomarker', 'CVi (%)', 'CVa (%)', 'RCV (%)', 'Source'],
        [
            ['HbA1c', '1.9', '1.5', '6.7', 'Aarsand 2018'],
            ['Fasting Blood Sugar', '5.7', '1.6', '16.5', 'Ricos 1999'],
            ['Post-Prandial Glucose', '12.4', '1.6', '34.7', 'Ricos 1999'],
            ['Total Cholesterol', '5.4', '1.6', '15.6', 'Aarsand 2018'],
            ['HDL Cholesterol', '7.1', '1.6', '20.2', 'Aarsand 2018'],
            ['LDL Cholesterol', '8.3', '2.0', '23.7', 'Ricos 1999'],
            ['Triglycerides', '20.9', '2.5', '58.3', 'Aarsand 2018'],
            ['Creatinine', '5.3', '2.2', '15.9', 'Aarsand 2018'],
            ['Blood Urea Nitrogen', '12.3', '2.1', '34.6', 'Ricos 1999'],
            ['eGFR', '5.3', '2.2', '15.9', 'Derived from Creatinine'],
            ['Uric Acid', '8.6', '1.7', '24.3', 'Aarsand 2018'],
            ['Hemoglobin', '2.8', '1.5', '8.8', 'Ricos 1999'],
            ['White Blood Cells', '11.4', '2.0', '32.2', 'Ricos 1999'],
            ['Ferritin', '14.2', '3.5', '40.6', 'Ricos 1999'],
            ['CRP', '42.0', '3.5', '116.8', 'Ricos 1999'],
            ['ESR', '18.2', '5.0', '52.3', 'Ricos 1999'],
            ['TSH', '19.3', '2.5', '54.1', 'Ricos 1999'],
            ['Vitamin D', '13.6', '5.0', '40.2', 'Ricos 1999'],
            ['Vitamin B12', '11.0', '5.0', '33.5', 'Ricos 1999'],
        ],
        col_widths=[3.5, 1.8, 1.8, 1.8, 3.0]
    )

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Clinical insight: ')
    run.bold = True
    p.add_run(
        'Note the extreme variation in RCV across biomarkers. CRP has an '
        'RCV of 116.8% -- meaning a CRP reading that doubles might still be '
        'within normal biological noise. In contrast, HbA1c has an RCV of '
        'only 6.7%, so even small changes are clinically meaningful. '
        'This is why a single universal noise threshold (like "2% of range") '
        'would produce false trends for high-variation markers and miss real '
        'trends for low-variation markers.'
    )

    # 5.3 Two-Tier Algorithm
    doc.add_heading('5.3 Two-Tier Trend Direction Algorithm', level=2)

    doc.add_paragraph(
        'The trend direction is computed using a two-tier analysis:'
    )

    doc.add_heading('Tier 1: Per-Step Analysis', level=3)
    doc.add_paragraph(
        'Each consecutive pair of readings is compared. The percentage change '
        'between each pair is calculated, and if it exceeds the biomarker\'s '
        'RCV threshold, it is counted as a "significant" step (either "up" '
        'or "down"). If any step exceeds RCV:'
    )
    doc.add_paragraph('All significant steps are "up" --> rising', style='List Bullet')
    doc.add_paragraph('All significant steps are "down" --> declining', style='List Bullet')
    doc.add_paragraph('Mixed directions --> fluctuating', style='List Bullet')

    doc.add_heading('Tier 2: Cumulative Drift Detection', level=3)
    doc.add_paragraph(
        'If no single step exceeds RCV (Tier 1 finds nothing), the algorithm '
        'checks whether the overall first-to-last change exceeds RCV AND '
        'all individual deltas are in the same direction (monotonic). '
        'This catches gradual cumulative drift.'
    )

    p = doc.add_paragraph()
    run = p.add_run('Example: ')
    run.bold = True
    p.add_run(
        'HbA1c readings 5.8% --> 6.1% --> 6.4%. Each consecutive step is '
        '+5.2% and +4.9% (both below 6.7% RCV). But the overall change '
        '(5.8 to 6.4 = +10.3%) exceeds RCV, and both steps are upward '
        '(monotonic). Tier 2 correctly classifies this as "rising."'
    )

    p = doc.add_paragraph()
    run = p.add_run('Clinical rationale (Fraser 2012): ')
    run.bold = True
    run.italic = True
    p.add_run(
        '"When serial results show a consistent trend, even if individual '
        'changes are within biological variation, the pattern itself may '
        'be clinically significant."'
    )

    # 5.4 Zone Classification
    doc.add_heading('5.4 Zone Classification', level=2)

    doc.add_paragraph(
        'The latest reading is classified into one of five zones relative '
        'to the laboratory reference range:'
    )

    add_styled_table(doc,
        ['Zone', 'Definition', 'Source'],
        [
            ['below_range', 'Value < reference_low', 'Lab reference range (CLSI EP28-A3c)'],
            ['borderline_low', 'Within range but within 10% of ref_low', 'Zivaa UX convention (not from guideline)'],
            ['in_range', 'Solidly within the reference interval', 'Lab reference range (CLSI EP28-A3c)'],
            ['borderline_high', 'Within range but within 10% of ref_high', 'Zivaa UX convention (not from guideline)'],
            ['above_range', 'Value > reference_high', 'Lab reference range (CLSI EP28-A3c)'],
        ],
        col_widths=[3.0, 5.5, 5.5]
    )

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Note: ')
    run.bold = True
    p.add_run(
        'The "borderline" sub-zones use a 10% threshold that is a Zivaa-defined '
        'UX convention, not from a published clinical guideline. This is explicitly '
        'documented in the code. The out-of-range zones (below_range, above_range) '
        'use the lab\'s own reference ranges, which are established per CLSI EP28-A3c.'
    )

    # 5.5 Clinical Flag Matrix
    doc.add_heading('5.5 Clinical Flag Decision Matrix', level=2)

    doc.add_paragraph(
        'The clinical flag combines trend direction and zone to produce '
        'an actionable interpretation. Two separate matrices are used:'
    )

    doc.add_heading('Standard Matrix (lower values = healthier)', level=3)
    doc.add_paragraph('Applies to: HbA1c, LDL, Creatinine, CRP, FBS, Triglycerides, etc.')

    add_styled_table(doc,
        ['Direction \\ Zone', 'below_range', 'in_range', 'above_range'],
        [
            ['rising', 'improving', 'stable', 'worsening'],
            ['declining', 'worsening', 'stable', 'improving'],
            ['stable', 'needs_attention', 'stable', 'needs_attention'],
            ['fluctuating', 'needs_attention', 'needs_attention', 'needs_attention'],
        ],
        col_widths=[3.0, 3.5, 3.5, 3.5]
    )

    doc.add_paragraph()
    doc.add_heading('Inverse Matrix (higher values = healthier)', level=3)
    doc.add_paragraph('Applies to: eGFR, HDL, Hemoglobin, B12, Vitamin D, Ferritin')

    add_styled_table(doc,
        ['Direction \\ Zone', 'below_range', 'in_range', 'above_range'],
        [
            ['rising', 'improving', 'stable', 'needs_attention'],
            ['declining', 'worsening', 'needs_attention', 'stable'],
            ['stable', 'needs_attention', 'stable', 'needs_attention'],
            ['fluctuating', 'needs_attention', 'needs_attention', 'needs_attention'],
        ],
        col_widths=[3.0, 3.5, 3.5, 3.5]
    )

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Important: ')
    run.bold = True
    p.add_run(
        'This decision matrix is a Zivaa-designed clinical heuristic. While each '
        'cell is logically defensible, no published clinical decision rule maps '
        'trend direction + zone to a single flag in this exact format. The matrix '
        'is designed to produce directionally correct interpretations for a '
        'caregiver-facing UI. For guideline-specific interpretations, see the '
        'Rate-of-Change Alerts in Section 5.7.'
    )

    # 5.6 Inverse Polarity
    doc.add_heading('5.6 Inverse-Polarity Biomarkers', level=2)

    doc.add_paragraph(
        'Six biomarkers where higher values indicate better health use '
        'the inverse decision matrix:'
    )

    add_styled_table(doc,
        ['Code', 'Name', 'Why Higher = Better', 'Source'],
        [
            ['EGFR', 'Estimated GFR', 'Higher = healthier kidney filtration', 'KDIGO 2024'],
            ['HDL', 'HDL Cholesterol', 'Higher = cardioprotective', 'ACC/AHA 2018'],
            ['HEMOGLOBIN', 'Hemoglobin', 'Higher = better O2 transport', 'WHO 2011'],
            ['B12', 'Vitamin B12', 'Higher = better neurological function', 'Standard clinical'],
            ['VITAMIN_D', '25-OH Vitamin D', 'Higher = better bone/immune health', 'Standard clinical'],
            ['FERRITIN', 'Serum Ferritin', 'Higher = better iron stores', 'Standard clinical'],
        ],
        col_widths=[2.5, 3.0, 5.0, 3.0]
    )

    # 5.7 Rate Alerts
    doc.add_heading('5.7 Rate-of-Change Alerts', level=2)

    doc.add_paragraph(
        'Unlike the general clinical flag (which is a Zivaa heuristic), '
        'rate-of-change alerts are triggered by published clinical guideline '
        'thresholds. These are the strongest evidence-based signals in the system.'
    )

    add_styled_table(doc,
        ['Biomarker', 'Threshold', 'Alert Label', 'Guideline'],
        [
            ['eGFR', 'Decline > 5 mL/min/year', 'rapid_progression', 'KDIGO 2024 CKD Guidelines'],
            ['HbA1c', 'Rise > 1.0%/year (~0.5%/6mo)', 'therapy_review_needed', 'ADA 2024 Standards of Care'],
        ],
        col_widths=[2.5, 4.0, 3.5, 5.0]
    )

    doc.add_paragraph()
    doc.add_paragraph(
        'Rate alerts appear as an optional rate_alert object in the API '
        'response, containing a label and the full citation string. They are '
        'only present when the threshold is exceeded.'
    )

    # ================================================================
    # 6. EXAMPLE OUTPUT
    # ================================================================
    doc.add_page_break()
    doc.add_heading('6. Example Output (Ranjit\'s Lab Data)', level=1)

    doc.add_paragraph(
        'The following table shows the trend analysis results for patient '
        'Ranjit (3 lab reports: January, March, and June 2026). This '
        'demonstrates how the RCV-based analysis correctly distinguishes '
        'real clinical trends from biological noise.'
    )

    add_styled_table(doc,
        ['Biomarker', 'Direction', 'RCV%', 'Change%', 'Flag', 'Rate Alert'],
        [
            ['HbA1c', 'rising', '6.7%', '+10.3%', 'worsening', 'ADA: therapy review'],
            ['eGFR', 'declining', '15.9%', '-25.6%', 'worsening', 'KDIGO: rapid progression'],
            ['Creatinine', 'rising', '15.9%', '+27.3%', 'worsening', '--'],
            ['CRP', 'rising', '116.8%', '+244.4%', 'worsening', '--'],
            ['Hemoglobin', 'declining', '8.8%', '-15.2%', 'worsening', '--'],
            ['Ferritin', 'declining', '40.5%', '-44.4%', 'worsening', '--'],
            ['TSH', 'rising', '53.9%', '+75.0%', 'worsening', '--'],
            ['HDL', 'stable', '20.2%', '-9.5%', 'needs_attention', '--'],
            ['Triglycerides', 'stable', '58.3%', '+10.8%', 'needs_attention', '--'],
            ['LDL', 'stable', '23.7%', '+8.5%', 'needs_attention', '--'],
            ['BUN', 'stable', '34.6%', '+16.7%', 'needs_attention', '--'],
        ],
        col_widths=[2.5, 2.0, 1.5, 2.0, 3.0, 4.5]
    )

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Key observations: ')
    run.bold = True

    doc.add_paragraph(
        'HDL (-9.5% change) is correctly classified as "stable" because its '
        'RCV is 20.2%. The 9.5% decline falls within normal biological noise.',
        style='List Bullet'
    )
    doc.add_paragraph(
        'Triglycerides (+10.8%) is correctly "stable" (RCV=58.3%). This '
        'biomarker has extreme within-subject variation.',
        style='List Bullet'
    )
    doc.add_paragraph(
        'HbA1c (+10.3%) is correctly "rising" via Tier 2 cumulative drift '
        'detection, even though each individual step (~5%) was below the '
        '6.7% RCV threshold.',
        style='List Bullet'
    )
    doc.add_paragraph(
        'eGFR triggers both a "worsening" clinical flag AND a KDIGO '
        '"rapid_progression" rate alert (declining ~48 mL/min/year, '
        'threshold is 5 mL/min/year).',
        style='List Bullet'
    )

    # ================================================================
    # 7. EVIDENCE STRENGTH
    # ================================================================
    doc.add_heading('7. Evidence Strength Assessment', level=1)

    doc.add_paragraph(
        'Each component of the trend analysis is rated for evidence strength:'
    )

    add_styled_table(doc,
        ['Component', 'Evidence Level', 'Source', 'Notes'],
        [
            ['RCV formula', 'STRONG', 'Fraser 1989, 2001, 2012', 'Gold standard for lab change significance'],
            ['CVi/CVa values', 'STRONG', 'EFLM database (Aarsand 2018, Ricos 1999)', 'Published and maintained by EFLM'],
            ['Two-tier analysis', 'MODERATE', 'Fraser 2001, 2012', 'Tier 2 (cumulative drift) is evidence-supported but not a formal published algorithm'],
            ['Rate alerts (eGFR)', 'STRONG', 'KDIGO 2024', 'Direct threshold from clinical practice guideline'],
            ['Rate alerts (HbA1c)', 'STRONG', 'ADA 2024', 'Direct threshold from standards of care'],
            ['Zone classification', 'STRONG (out-of-range), MODERATE (borderline)', 'CLSI EP28-A3c / Zivaa', 'Out-of-range uses lab ranges; borderline 10% is Zivaa convention'],
            ['Clinical flag matrix', 'MODERATE', 'Zivaa heuristic', 'Logically defensible but not a published decision rule'],
            ['Inverse polarity', 'STRONG', 'KDIGO, ACC/AHA, WHO', 'Standard clinical knowledge'],
        ],
        col_widths=[3.0, 2.5, 4.0, 5.5]
    )

    # ================================================================
    # 8. CITATIONS
    # ================================================================
    doc.add_page_break()
    doc.add_heading('8. Citations & References', level=1)

    citations = [
        ('Aarsand AK, Fernandez-Calle P, Webster C, et al.',
         '"The EuBIVAS: Within- and Between-Subject Biological Variation Data for Electrolytes, Lipids, Urea, Uric Acid, Total Protein, Total Bilirubin, Direct Bilirubin, and Glucose."',
         'Clin Chem. 2018;64(9):1380-1393.'),

        ('Ricos C, Alvarez V, Cava F, et al.',
         '"Current databases on biological variation: pros, cons and progress."',
         'Scand J Clin Lab Invest. 1999;59(7):491-500.'),

        ('Fraser CG.',
         '"Biological Variation: From Principles to Practice."',
         'AACC Press, 2001. ISBN: 978-1890883492.'),

        ('Fraser CG.',
         '"Reference change values."',
         'Clin Chem Lab Med. 2012;50(5):807-812.'),

        ('Fraser CG, Harris EK.',
         '"Generation and application of data on biological variation in clinical chemistry."',
         'Crit Rev Clin Lab Sci. 1989;27(5):409-437.'),

        ('KDIGO.',
         '"Clinical Practice Guideline for Evaluation and Management of Chronic Kidney Disease."',
         'Kidney Int Suppl. 2024;14(4S):e1-e314.'),

        ('American Diabetes Association (ADA).',
         '"Standards of Care in Diabetes -- 2024."',
         'Diabetes Care. 2024;47(Suppl 1):S1-S321.'),

        ('Grundy SM, Stone NJ, Bailey AL, et al.',
         '"2018 AHA/ACC/AACVPR/AAPA/ABC/ACPM/ADA/AGS/APhA/ASPC/NLA/PCNA Guideline on the Management of Blood Cholesterol."',
         'J Am Coll Cardiol. 2019;73(24):e285-e350.'),

        ('World Health Organization.',
         '"Haemoglobin concentrations for the diagnosis of anaemia and assessment of severity."',
         'Vitamin and Mineral Nutrition Information System. 2011.'),

        ('CLSI.',
         '"Defining, Establishing, and Verifying Reference Intervals in the Clinical Laboratory."',
         'EP28-A3c. 3rd ed. 2010.'),

        ('EFLM Biological Variation Database.',
         'https://biologicalvariation.eu/',
         'Accessed June 2026.'),
    ]

    for i, (authors, title, journal) in enumerate(citations, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        run = p.add_run(f'[{i}] ')
        run.bold = True
        p.add_run(f'{authors} ')
        run = p.add_run(title)
        run.italic = True
        p.add_run(f' {journal}')

    # ================================================================
    # SAVE
    # ================================================================
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    doc.save(OUTPUT_PATH)
    print(f"Document saved to: {OUTPUT_PATH}")
    return OUTPUT_PATH


if __name__ == "__main__":
    path = build_document()
    print(f"Successfully generated: {path}")
