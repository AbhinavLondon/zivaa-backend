import sys
import os
from datetime import datetime, timezone, timedelta

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.insights.data_fetcher import supabase
from app.services.insights.cta_resolver import resolve_ctas

SHYAM_ID = "0c445588-b36c-478f-9be3-2addfc77dc1c"
PATIENT_NAME = "Shyam"

now = datetime.now(timezone.utc)

nudges_def = [
    # 1. Sepsis Level 3 Emergency
    {
        "risk_level": "HIGH",
        "nudge_title": "Urgent Health Alert: High Fever & Elevated Pulse Detected",
        "nudge_text": f"{PATIENT_NAME}'s body temperature spiked to 38.6°C alongside a resting heart rate of 108 bpm and 18 nocturnal coughs. This combination indicates severe acute infection or sepsis requiring immediate medical evaluation.",
        "why_flagged": {
            "summary": "Resting pulse climbed 40 bpm above baseline in response to a +1.6°C skin temperature rise, exceeding Liebermeister's physiological response threshold. Night microphone logged frequent coughing bouts.",
            "primary_vitals": [
                {"name": "Body Temperature", "value": "38.6°C", "usual": "37.0°C", "description": "Fever spike of +1.6°C recorded overnight."},
                {"name": "Resting Heart Rate", "value": "108 bpm", "usual": "68 bpm", "description": "Severe resting tachycardia exceeding physiological limits."}
            ],
            "supporting_vitals": [
                {"name": "Nocturnal Coughs", "value": "18 coughs", "usual": "1 cough", "description": "Acoustic audio sensors logged frequent coughing bouts."}
            ],
            "conclusion": "The co-occurrence of fever, pronounced tachycardia, and coughing indicates acute infection with high sepsis risk."
        },
        "action_steps_input": {
            "title": "Immediate Emergency Medical Transfer",
            "title_emphasis": "CRITICAL",
            "description": f"Do not wait. Have {PATIENT_NAME} sit in a recovery position and seek emergency medical casualty transport.",
            "selected_domain": "occult_infection_sepsis",
            "escalation_level": "level_3_acute_emergency"
        }
    },

    # 2. Sepsis Level 2 Longitudinal Escalation (Active >48h)
    {
        "risk_level": "MEDIUM",
        "nudge_title": "Follow-Up: Low-Grade Temperature & Pulse Elevation Persisting for 48 Hours",
        "nudge_text": f"Subtle temperature elevation (+0.9°C) and resting tachycardia (82 bpm) have now persisted across 3 consecutive days for {PATIENT_NAME}. We recommend scheduling at-home blood and urine laboratory tests today.",
        "why_flagged": {
            "summary": "This physiological temperature drift and mild tachycardia has failed to normalize over 48 hours. In older adults, persistent sub-febrile shifts frequently represent occult urinary tract or chest infections.",
            "primary_vitals": [
                {"name": "Skin Temperature Delta", "value": "+0.9°C", "usual": "0.0°C", "description": "Elevated above baseline for 3 consecutive nights."},
                {"name": "Resting Heart Rate", "value": "82 bpm", "usual": "68 bpm", "description": "Resting heart rate remains 14 bpm above personal average."}
            ],
            "supporting_vitals": [
                {"name": "Walking Cadence", "value": "64 spm", "usual": "84 spm", "description": "Daily movement speed has gradually slowed."}
            ],
            "conclusion": "Persistent low-grade temperature drift warrants blood and urine screening to identify and treat early infection."
        },
        "action_steps_input": {
            "title": "Stat Diagnostic Phlebotomy & Urine Test",
            "title_emphasis": "RECOMMENDED",
            "description": f"Book home sample collection for CBC and Urine Routine, and share the 3-day vital history with {PATIENT_NAME}'s family doctor.",
            "selected_domain": "occult_infection_sepsis",
            "escalation_level": "level_2_diagnostic_investigation",
            "escalation_reason": "Longitudinal Escalation: This physiological anomaly has persisted for over 48 hours without resolution. Stepping up to at-home diagnostic review."
        }
    },

    # 3. Infection Level 1 Bedside Triage
    {
        "risk_level": "LOW",
        "nudge_title": "Early Health Note: Slight Temperature Shift Observed Last Night",
        "nudge_text": f"We noticed a slight +0.8°C shift in {PATIENT_NAME}'s skin temperature last night. While vitals remain stable, simple bedside hydration and an oral temperature check are advised this morning.",
        "why_flagged": {
            "summary": "Skin temperature was mildly elevated overnight. Morning pulse and activity are currently stable, but early hydration helps support the body's immune defenses.",
            "primary_vitals": [
                {"name": "Skin Temperature Delta", "value": "+0.8°C", "usual": "0.0°C", "description": "Mild elevation above personal nightly baseline."}
            ],
            "supporting_vitals": [
                {"name": "Resting Heart Rate", "value": "73 bpm", "usual": "68 bpm", "description": "Heart rate is near normal baseline."}
            ],
            "conclusion": "A minor thermal deviation that can be supported with proactive fluids and simple monitoring."
        },
        "action_steps_input": {
            "title": "Bedside Check & Fluids",
            "title_emphasis": "WATCHFUL WAITING",
            "description": f"Offer {PATIENT_NAME} a glass of warm water or ORS, check oral temperature, and ensure comfortable room ventilation.",
            "selected_domain": "occult_infection_sepsis",
            "escalation_level": "level_1_bedside_triage"
        }
    },

    # 4. Respiratory Level 3 Emergency
    {
        "risk_level": "HIGH",
        "nudge_title": "Critical Alert: Severe Nocturnal Oxygen Drop & Rapid Breathing",
        "nudge_text": f"Blood oxygen dipped to a critical nadir of 86% during sleep with respiratory rate spiking to 26 breaths/min. Immediate clinical assessment and emergency oxygen support are required.",
        "why_flagged": {
            "summary": "Oxygen saturation dropped severely below the British Thoracic Society critical safety threshold of 88%, accompanied by compensatory rapid breathing (NEWS2 Score 3).",
            "primary_vitals": [
                {"name": "Minimum Oxygen (SpO2)", "value": "86%", "usual": "96%", "description": "Severe desaturation during overnight sleep."},
                {"name": "Respiratory Rate", "value": "26 RPM", "usual": "15 RPM", "description": "Tachypnea indicating cardiopulmonary strain."}
            ],
            "supporting_vitals": [
                {"name": "Acoustic Snoring Events", "value": "14 events", "usual": "2 events", "description": "Multiple gasping and snoring events detected."}
            ],
            "conclusion": "Critically low oxygen levels with high respiratory rate require emergency medical transfer."
        },
        "action_steps_input": {
            "title": "Emergency Medical Evaluation Required",
            "title_emphasis": "IMMEDIATE ACTION",
            "description": f"Have {PATIENT_NAME} sit completely upright and call 108 emergency ambulance immediately.",
            "selected_domain": "respiratory_hypoxemia_osa",
            "escalation_level": "level_3_acute_emergency"
        }
    },

    # 5. Respiratory Level 2 Diagnostics (OSA)
    {
        "risk_level": "MEDIUM",
        "nudge_title": "Sleep Pattern Flag: Nighttime Oxygen Dips & Regular Snoring Detected",
        "nudge_text": f"{PATIENT_NAME}'s oxygen saturation dropped to 90% last night alongside 9 snoring events recorded by acoustic sensors. This pattern is characteristic of Obstructive Sleep Apnea.",
        "why_flagged": {
            "summary": "Oxygen saturation fell below the 92% clinical threshold during sleep sessions with concurrent snoring, and deep restorative sleep dropped to only 32 minutes.",
            "primary_vitals": [
                {"name": "Minimum Oxygen (SpO2)", "value": "90%", "usual": "96%", "description": "Nocturnal desaturation below target range."},
                {"name": "Snoring Events", "value": "9 events", "usual": "1 event", "description": "Phone microphone logged recurrent acoustic airway vibration."}
            ],
            "supporting_vitals": [
                {"name": "Deep Sleep Duration", "value": "32 mins", "usual": "75 mins", "description": "Deep restorative sleep was heavily fragmented."}
            ],
            "conclusion": "Nocturnal hypoxemia combined with acoustic snoring indicates high probability of obstructive sleep apnea."
        },
        "action_steps_input": {
            "title": "Home Sleep Apnea Test (HSAT)",
            "title_emphasis": "DIAGNOSTIC TEST",
            "description": f"Order an at-home sleep apnea testing device to monitor airflow and breathing patterns throughout the night.",
            "selected_domain": "respiratory_hypoxemia_osa",
            "escalation_level": "level_2_diagnostic_investigation"
        }
    },

    # 6. Respiratory Level 1 Bedside Triage
    {
        "risk_level": "LOW",
        "nudge_title": "Sleep Breathing Check: Borderline Nighttime Oxygen Dip Observed",
        "nudge_text": f"A brief dip in oxygen to 93% was observed during {PATIENT_NAME}'s sleep. Adjusting sleeping posture and elevating the head of the bed can help keep airways clear.",
        "why_flagged": {
            "summary": "Oxygen saturation dipped slightly below the standard 94% threshold. Breathing rate and heart rate remained stable.",
            "primary_vitals": [
                {"name": "Minimum Oxygen (SpO2)", "value": "93%", "usual": "96%", "description": "Mild, brief dip during early morning sleep."}
            ],
            "supporting_vitals": [
                {"name": "Respiratory Rate", "value": "16 RPM", "usual": "15 RPM", "description": "Normal breathing rate throughout sleep."}
            ],
            "conclusion": "A minor nocturnal dip that usually responds well to sleep position adjustments."
        },
        "action_steps_input": {
            "title": "Adjust Sleep Posture & Spot Check",
            "title_emphasis": "SIMPLE ADJUSTMENT",
            "description": f"Use an extra pillow to elevate {PATIENT_NAME}'s head 30 degrees and encourage sleeping on their side tonight.",
            "selected_domain": "respiratory_hypoxemia_osa",
            "escalation_level": "level_1_bedside_triage"
        }
    },

    # 7. Sarcopenia Level 3 Acute Fall Danger Under Exhaustion
    {
        "risk_level": "HIGH",
        "nudge_title": "Fall Safety Warning: High Movement at Shuffling Pace After Severe Sleep Loss",
        "nudge_text": f"{PATIENT_NAME} has completed over 4,200 steps at a cautious, shuffling pace of 54 steps/min following only 4.1 hours of fragmented sleep. Fatigue dramatically increases tripping risk today.",
        "why_flagged": {
            "summary": "High physical exposure (4,200 steps) with compromised gait kinematics (cadence 54 spm, sit-to-stand 18.2s) under acute sleep deprivation multiplies fall risk threefold per AGS guidelines.",
            "primary_vitals": [
                {"name": "Walking Cadence", "value": "54 spm", "usual": "88 spm", "description": "Severe gait slowing with cautious, shuffling strides."},
                {"name": "Sleep Duration", "value": "4.1 hrs", "usual": "7.2 hrs", "description": "Severe sleep deficit impairs balance and reflexes."}
            ],
            "supporting_vitals": [
                {"name": "Sit-to-Stand Duration", "value": "18.2s", "usual": "8.5s", "description": "Chair rise is significantly delayed and unsteady."},
                {"name": "Total Steps", "value": "4,200 steps", "usual": "3,000 steps", "description": "High active walking exposure on exhausted legs."}
            ],
            "conclusion": "Severe physical fatigue combined with a shuffling gait creates an acute danger of falling."
        },
        "action_steps_input": {
            "title": "Immediate Fall Prevention Protocol",
            "title_emphasis": "HIGH FALL RISK",
            "description": f"Supervise {PATIENT_NAME}'s walking closely today, ensure non-skid footwear, and encourage rest to recover balance.",
            "selected_domain": "sarcopenia_fall_prevention",
            "escalation_level": "level_3_acute_emergency"
        }
    },

    # 8. Sarcopenia Level 2 Physiotherapy Review
    {
        "risk_level": "MEDIUM",
        "nudge_title": "Mobility Trend: Walking Speed & Daily Movement Have Declined Over 2 Weeks",
        "nudge_text": f"{PATIENT_NAME}'s 14-day median walking cadence has dropped to 62 steps/min with active movement time under 20 minutes daily. An at-home physiotherapy review will help rebuild leg strength.",
        "why_flagged": {
            "summary": "Walking cadence below 65 spm (corresponding to <0.8 m/s) meets EWGSOP2 European consensus criteria for progressive sarcopenia and muscle weakness.",
            "primary_vitals": [
                {"name": "Walking Cadence", "value": "62 spm", "usual": "86 spm", "description": "Two-week median cadence indicates slowing gait speed."},
                {"name": "Active Movement Time", "value": "16 mins", "usual": "45 mins", "description": "Daily walking duration is severely restricted."}
            ],
            "supporting_vitals": [
                {"name": "Active Daytime Hours", "value": "4/12 hrs", "usual": "8/12 hrs", "description": "Movement is fragmented into prolonged sitting."}
            ],
            "conclusion": "A progressive decline in walking speed suggests developing sarcopenia that benefits from targeted physical therapy."
        },
        "action_steps_input": {
            "title": "Home Geriatric Physiotherapy Assessment",
            "title_emphasis": "STRENGTH & BALANCE",
            "description": f"Book an at-home physiotherapy session for a formal balance test and gentle quadriceps strengthening exercises.",
            "selected_domain": "sarcopenia_fall_prevention",
            "escalation_level": "level_2_diagnostic_investigation"
        }
    },

    # 9. Cardiorenal Level 2 Fluid Retention
    {
        "risk_level": "MEDIUM",
        "nudge_title": "Cardiovascular Trend: Rapid Weight Gain & Lost Nighttime Heart Rate Dip",
        "nudge_text": f"{PATIENT_NAME} gained 2.1 kg over the last 3 days while their night heart rate remained elevated at 76 bpm. This combination suggests early fluid retention and volume overload.",
        "why_flagged": {
            "summary": "Weight gain exceeding 1.5 kg in 72 hours alongside a non-dipping nighttime heart rate profile indicates persistent sympathetic activation and fluid redistribution.",
            "primary_vitals": [
                {"name": "3-Day Weight Gain", "value": "+2.1 kg", "usual": "0.0 kg", "description": "Rapid fluid buildup exceeding AHA threshold (>0.9kg/day)."},
                {"name": "Night Heart Rate", "value": "76 bpm", "usual": "60 bpm", "description": "Loss of normal 10-20% nocturnal dip (Non-Dipping profile)."}
            ],
            "supporting_vitals": [
                {"name": "Awakenings > 5 mins", "value": "4 events", "usual": "1 event", "description": "Frequent nighttime awakenings likely due to nocturia."}
            ],
            "conclusion": "Rapid weight gain with lost nocturnal cardiac dip indicates fluid retention that warrants renal and diuretic review."
        },
        "action_steps_input": {
            "title": "Kidney Labs & Medication Review",
            "title_emphasis": "FLUID CHECK",
            "description": f"Order home blood tests for Creatinine and Electrolytes, and check {PATIENT_NAME}'s ankles for swelling.",
            "selected_domain": "cardiorenal_fluid_balance",
            "escalation_level": "level_2_diagnostic_investigation"
        }
    },

    # 10. Cardiac Level 3 Hypertensive Emergency
    {
        "risk_level": "HIGH",
        "nudge_title": "Urgent Medical Alert: Severe Blood Pressure Surge (184/110 mmHg)",
        "nudge_text": f"Blood pressure reading of 184/110 mmHg recorded this morning with pulse at 104 bpm. Per ACC/AHA clinical guidelines, readings above 180 mmHg require immediate medical intervention.",
        "why_flagged": {
            "summary": "Blood pressure has escalated directly into the Hypertensive Urgency category (Systolic >= 180 mmHg). Resting tachycardia further indicates acute cardiovascular stress.",
            "primary_vitals": [
                {"name": "Blood Pressure", "value": "184/110", "usual": "128/82", "description": "Severe spike exceeding 180 mmHg urgency cutoff."},
                {"name": "Heart Rate", "value": "104 bpm", "usual": "72 bpm", "description": "Tachycardia accompanying the pressure surge."}
            ],
            "supporting_vitals": [
                {"name": "Heart Rate Recovery", "value": "6 bpm", "usual": "16 bpm", "description": "Blunted 1-min vagal heart rate recovery."}
            ],
            "conclusion": "Severe systolic surge above 180 mmHg requires urgent medical evaluation to prevent complications."
        },
        "action_steps_input": {
            "title": "Immediate Clinical Evaluation Required",
            "title_emphasis": "HYPERTENSIVE URGENCY",
            "description": f"Have {PATIENT_NAME} sit quietly, check for headache or chest tightness, and call emergency medical services immediately.",
            "selected_domain": "cardio_autonomic_strain",
            "escalation_level": "level_3_acute_emergency"
        }
    },

    # 11. Metabolic Level 2 Glycemic Spike Post Deep Sleep Loss
    {
        "risk_level": "MEDIUM",
        "nudge_title": "Metabolic Flag: High Morning Blood Sugar Following Poor Deep Sleep",
        "nudge_text": f"{PATIENT_NAME}'s fasting blood sugar was 146 mg/dL this morning following only 28 minutes of deep restorative sleep last night. Deep sleep depletion significantly blunts insulin sensitivity.",
        "why_flagged": {
            "summary": "Deep sleep (slow-wave Stage 5) dropped below 45 minutes, directly driving next-day insulin resistance as documented in PNAS medical research.",
            "primary_vitals": [
                {"name": "Deep Sleep Duration", "value": "28 mins", "usual": "70 mins", "description": "Severe depletion of slow-wave Stage 5 sleep."},
                {"name": "Morning Blood Sugar", "value": "146 mg/dL", "usual": "105 mg/dL", "description": "Fasting glucose elevated above ADA 130 target."}
            ],
            "supporting_vitals": [
                {"name": "Awakenings Count", "value": "6 times", "usual": "2 times", "description": "High sleep fragmentation disrupted hormonal balance."}
            ],
            "conclusion": "Lack of deep sleep has temporarily elevated insulin resistance, leading to morning glycemic spikes."
        },
        "action_steps_input": {
            "title": "Fasting Metabolic Lab Review",
            "title_emphasis": "GLYCEMIC CONTROL",
            "description": f"Schedule an at-home fasting blood glucose and HbA1c panel to assess 3-month glycemic stability.",
            "selected_domain": "sleep_metabolic_dysregulation",
            "escalation_level": "level_2_diagnostic_investigation"
        }
    },

    # 12. Longevity Level 1 Wellness Maintenance
    {
        "risk_level": "LOW",
        "nudge_title": "Vitality Celebration: Outstanding Walking Cadence & Deep Sleep Rest",
        "nudge_text": f"{PATIENT_NAME} achieved an exceptional brisk walking cadence of 89 steps/min across 9 active daytime hours yesterday, followed by 78 minutes of deep restorative sleep last night.",
        "why_flagged": {
            "summary": "All primary biomarkers are operating in optimal longevity ranges. Cadence exceeds the WHO 85 spm brisk senior threshold and sleep architecture shows full restorative cycles.",
            "primary_vitals": [
                {"name": "Walking Cadence", "value": "89 spm", "usual": "82 spm", "description": "Brisk functional walking speed exceeding WHO standard."},
                {"name": "Active Daytime Hours", "value": "9/12 hrs", "usual": "6/12 hrs", "description": "Circadian movement distributed cleanly across waking day."}
            ],
            "supporting_vitals": [
                {"name": "Deep Sleep Duration", "value": "78 mins", "usual": "65 mins", "description": "Deep restorative sleep was fully achieved."}
            ],
            "conclusion": "Excellent functional vitality and restful sleep demonstrate strong cardiovascular and physical resilience."
        },
        "action_steps_input": {
            "title": "Maintain Vitality & Longevity Routine",
            "title_emphasis": "WELL DONE",
            "description": f"Celebrate this healthy milestone with {PATIENT_NAME} and review their monthly progress report together.",
            "selected_domain": "wellness_vitality_reinforcement",
            "escalation_level": "level_1_bedside_triage"
        }
    }
]

print(f"Refreshing 12 dummy nudges for {PATIENT_NAME} (ID: {SHYAM_ID})...")

try:
    del_res = supabase.table("nudge_alerts").delete().eq("patient_id", SHYAM_ID).eq("source", "clinical_test_suite").execute()
    print(f"Cleaned up previous test alerts.")
except Exception as e:
    print(f"Note on cleanup: {e}")

created_count = 0
for idx, item in enumerate(nudges_def, 1):
    # Process through cta_resolver so buttons, checklists, and tiers are injected
    resolved_action_steps = resolve_ctas(
        item["action_steps_input"],
        risk_level=item["risk_level"],
        patient_id=SHYAM_ID
    )

    # Offset timestamps slightly so they appear sequentially in feed (from 12 mins ago to now)
    timestamp = (now - timedelta(minutes=(12 - idx) * 3)).isoformat()

    nudge_payload = {
        "patient_id": SHYAM_ID,
        "risk_level": item["risk_level"],
        "nudge_title": item["nudge_title"],
        "nudge_text": item["nudge_text"],
        "why_flagged": item["why_flagged"],
        "action_steps": resolved_action_steps,
        "source": "clinical_test_suite",
        "acknowledged": False,
        "created_at": timestamp
    }

    try:
        res = supabase.table("nudge_alerts").insert(nudge_payload).execute()
        if res.data:
            created_count += 1
            print(f"[{idx}/12] Created: '{item['nudge_title'][:45]}...' -> Tier: {resolved_action_steps.get('escalation_tier')}")
        else:
            print(f"[{idx}/12] Failed to insert: {res}")
    except Exception as e:
        print(f"[{idx}/12] Error inserting nudge: {e}")

print(f"\nSUCCESS: Successfully inserted {created_count} / 12 dummy clinical nudges for {PATIENT_NAME}!")
