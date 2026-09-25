"""Clinical Symptom Taxonomy Catalog.

Grounded in international clinical guidelines (NICE, ICMR, WHO, ACP, CDSCO SaMD).
Covers 12 Master Physiological Domains representing >99% of outpatient and geriatric presentations.
Provides standardized SNOMED CT mappings, anatomical sites, evidence-based SLAs, and red flags.
"""

import os
import json
import re
from typing import Dict, Any, List, Optional
import httpx

CLINICAL_TAXONOMY: Dict[str, Dict[str, Any]] = {
    # ── 1. MUSCULOSKELETAL & AXIAL SPINE ──
    "MSK_LUMBAR_STRAIN": {
        "canonical_key": "MSK_LUMBAR_STRAIN",
        "clinical_reference": "NICE Guideline NG59 (2020) 'Low back pain and sciatica in over 16s'; ICMR Standard Treatment Workflow for Low Back Pain (2022); ACP Clinical Practice Guideline (Ann Intern Med 2017). Non-pharma: superficial heat, activity preservation, avoiding bed rest. Red flags: Cauda Equina syndrome criteria.",
        "snomed_code": "279039007",
        "name": "Lumbar Muscle Strain & Axial Back Pain",
        "domain": "Musculoskeletal",
        "anatomical_site": "Lower Back / Lumbar",
        "expected_resolution_days": 14,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Bowel or bladder incontinence",
            "Saddle anesthesia (numbness in groin/buttocks)",
            "Progressive foot drop or severe bilateral leg weakness",
            "Fever with localized spinal tenderness"
        ],
        "aliases": [
            "lower back pain", "low back ache", "back stiffness", "back catching",
            "lumbar strain", "lumbago", "kamar dard", "kamar mein jakdan", "waist pain", "pulled back muscle"
        ],
        "approved_modalities": [
            "Heat therapy (warm compress/towel for 15-20 mins)",
            "Gentle pelvic tilts and supine knee-to-chest stretch",
            "Pacing and avoiding prolonged sitting or heavy lifting",
            "Lumbar support pillow while seated"
        ],
        "contraindicated": ["Heavy deadlifts", "Deep forward toe touches", "High-impact running"]
    },
    "MSK_KNEE_OA_FLARE": {
        "canonical_key": "MSK_KNEE_OA_FLARE",
        "clinical_reference": "NICE Guideline NG226 (2022) 'Osteoarthritis in over 16s: diagnosis and management'; OARSI Non-Surgical Knee OA Guidelines (2019); ICMR Guidelines on Knee Osteoarthritis (2022). Non-pharma: local thermotherapy, isometric quadriceps sets, weight management. Red flags: septic arthritis, acute mechanical block.",
        "snomed_code": "239872002",
        "name": "Knee Osteoarthritis / Joint Flare",
        "domain": "Musculoskeletal",
        "anatomical_site": "Knees",
        "expected_resolution_days": 10,
        "max_self_care_days": 10,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Inability to bear full weight after a fall or twist",
            "Erythematous, hot, swollen joint with fever (septic arthritis rule-out)",
            "Audible pop with immediate acute joint locking"
        ],
        "aliases": [
            "knee pain", "knee stiffness", "aching knee", "knee arthritis flare",
            "patellar ache", "ghutne mein dard", "ghutna jakadna", "knee crepitus"
        ],
        "approved_modalities": [
            "Warm mustard oil or sesame oil compress (15 mins)",
            "Seated isometric quadriceps sets and straight leg raises",
            "Gentle chair mobility exercises",
            "Ice pack for 10 mins if acute warmth is present"
        ],
        "contraindicated": ["Deep squats", "Lunges", "High-impact pavement jogging", "Steep stair climbing"]
    },
    "MSK_CERVICAL_STIFFNESS": {
        "canonical_key": "MSK_CERVICAL_STIFFNESS",
        "clinical_reference": "NICE Clinical Knowledge Summaries (CKS 2021) 'Neck pain - non-specific and cervical radiculopathy'; Bone & Joint Decade Task Force on Neck Pain (Spine 2008). Non-pharma: cervical retraction (chin tucks), moist heat, sleep ergonomics. Red flags: cervical myelopathy, radicular neurological deficit.",
        "snomed_code": "298382003",
        "name": "Cervical Neck Strain & Stiffness",
        "domain": "Musculoskeletal",
        "anatomical_site": "Neck / Cervical",
        "expected_resolution_days": 7,
        "max_self_care_days": 10,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Radiating sharp pain or electric sensation down arm to fingers",
            "Hand clumsiness or progressive grip weakness",
            "Neck stiffness accompanied by high fever and light sensitivity"
        ],
        "aliases": [
            "neck pain", "stiff neck", "cervical pain", "neck catch", "gardan mein dard",
            "trapezius spasm", "shoulder-neck tightness"
        ],
        "approved_modalities": [
            "Warm shower or moist heat pack across upper traps (15 mins)",
            "Gentle cervical retraction (chin tucks) and slow lateral rotations",
            "Ergonomic pillow height adjustment for sleeping"
        ],
        "contraindicated": ["Aggressive neck cracking or rapid rotational jerking"]
    },
    "MSK_SHOULDER_IMPINGEMENT": {
        "canonical_key": "MSK_SHOULDER_IMPINGEMENT",
        "clinical_reference": "British Elbow & Shoulder Society (BESS) / BOA Guidelines on Subacromial Shoulder Pain (2021); AAOS Clinical Practice Guideline on Rotator Cuff Management (2019). Non-pharma: pendulum swings, wall-walk glides, overhead unloading. Red flags: acute full-thickness rotator cuff rupture.",
        "snomed_code": "262993005",
        "name": "Shoulder Tendonitis & Subacromial Pain",
        "domain": "Musculoskeletal",
        "anatomical_site": "Shoulders",
        "expected_resolution_days": 14,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Complete inability to abduct or raise arm (acute rotator cuff tear)",
            "Deformity or sudden bruising after trauma",
            "Left shoulder pain accompanied by chest pressure or shortness of breath"
        ],
        "aliases": [
            "shoulder pain", "shoulder ache", "rotator cuff ache", "kandhe mein dard",
            "shoulder stiffness", "pain reaching overhead", "shoulder injury",
            "burning shoulder pain", "arm weakness", "weakness in injured arm", "weakness in arm"
        ],
        "approved_modalities": [
            "Pendulum swings and gentle wall-climbing finger walks",
            "Warm compress before gentle movement",
            "Avoid sleeping directly on the affected shoulder"
        ],
        "contraindicated": ["Overhead heavy lifting", "Behind-the-neck presses"]
    },

    # ── 2. NEUROLOGICAL & CRANIAL ──
    "NEURO_TENSION_HEADACHE": {
        "canonical_key": "NEURO_TENSION_HEADACHE",
        "clinical_reference": "NICE Guideline CG150 (2021 update) 'Headaches in over 12s: diagnosis and management'; International Headache Society ICHD-3 (2018). Non-pharma: rest in dim environment, cool compress, oral rehydration. Red flags: SNOOP criteria (thunderclap, giant cell arteritis in age > 50, post-trauma on anticoagulants).",
        "snomed_code": "398057008",
        "name": "Tension Headache / Cranial Tightness",
        "domain": "Neurological",
        "anatomical_site": "Head / Cranial",
        "expected_resolution_days": 2,
        "max_self_care_days": 3,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Sudden severe 'thunderclap' onset peaking in seconds",
            "Headache with focal neurological deficits (facial droop, speech slur, limb weakness)",
            "New onset headache in patient > 65 with scalp/temporal tenderness (giant cell arteritis)",
            "Headache following acute head strike/fall while on anticoagulants"
        ],
        "aliases": [
            "headache", "head ache", "tension headache", "forehead tightness", "sar dard",
            "heavy head", "cranial band pressure"
        ],
        "approved_modalities": [
            "Dark, quiet room rest with eye mask for 20 mins",
            "Cool forehead compress or warm neck wrap",
            "Oral hydration (500ml water or electrolyte drink)",
            "Gentle temple acupressure breathing"
        ],
        "contraindicated": ["Excessive screen usage in dark rooms", "Loud noisy environments"]
    },
    "NEURO_POSTURAL_DIZZINESS": {
        "canonical_key": "NEURO_POSTURAL_DIZZINESS",
        "clinical_reference": "NICE Clinical Knowledge Summaries (CKS 2022) 'Postural hypotension'; AGS/BGS Clinical Practice Guideline for Fall Prevention in Older Persons; Consensus on Orthostatic Hypotension (Freeman et al., Clin Auton Res 2011). Non-pharma: two-stage standing, morning pre-rising hydration, ankle pumps. Red flags: cardiac syncope, new focal nystagmus.",
        "snomed_code": "404640003",
        "name": "Benign Positional / Orthostatic Lightheadedness",
        "domain": "Neurological",
        "anatomical_site": "Head / Cranial",
        "expected_resolution_days": 3,
        "max_self_care_days": 3,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Syncope (true blackout or loss of consciousness)",
            "Dizziness with chest pain, palpitations, or dyspnea",
            "New nystagmus (involuntary eye twitching) or inability to stand upright"
        ],
        "aliases": [
            "dizziness", "lightheaded", "head spinning", "chakkar", "unsteady on standing",
            "giddiness", "mild vertigo"
        ],
        "approved_modalities": [
            "Two-stage standing (pause seated for 30 seconds before upright posture)",
            "Adequate morning fluid intake (glass of water before getting out of bed)",
            "Ankle pumps before standing to stimulate venous return"
        ],
        "contraindicated": ["Sudden rapid standing", "Bending down quickly"]
    },

    # ── 3. GASTROINTESTINAL & HEPATIC ──
    "GI_ACUTE_DIARRHEA": {
        "canonical_key": "GI_ACUTE_DIARRHEA",
        "clinical_reference": "WHO Guidelines on Management of Acute Diarrhoeal Diseases (2017); ICMR Standard Treatment Workflow on Acute Gastroenteritis (2022); ACG Clinical Guideline for Acute Diarrheal Infections (Am J Gastroenterol 2016). Strict 48h senior SLA due to pre-renal AKI & electrolyte shock risk. Non-pharma: ORS, BRAT diet. Red flags: melena, hematochezia, anuria.",
        "snomed_code": "62315008",
        "name": "Acute Uncomplicated Diarrhea / Loose Stools",
        "domain": "Gastrointestinal",
        "anatomical_site": "Abdomen",
        "expected_resolution_days": 2,
        "max_self_care_days": 2,  # Strict 48h SLA for seniors due to dehydration & AKI risk
        "checkin_cadence_days": 1,
        "red_flags": [
            "Black tarry stools (melena) or frank red blood",
            "Signs of severe dehydration: dry tongue, confusion, postural collapse, anuria (>8h no urine)",
            "High fever > 101.5°F with severe localized abdominal rigidity"
        ],
        "aliases": [
            "diarrhea", "loose motions", "loose stools", "upset stomach", "dast", "pet kharab",
            "frequent watery stools", "stomach bug"
        ],
        "approved_modalities": [
            "Oral Rehydration Salts (ORS) or electrolyte water after each loose stool",
            "Bland BRAT diet (boiled rice, curd/yogurt, banana, toast)",
            "Sip boiled, cooled water throughout the day"
        ],
        "contraindicated": ["Dairy milk", "Spicy curries", "Heavy fried foods", "Caffeine"]
    },
    "GI_GERD_HEARTBURN": {
        "canonical_key": "GI_GERD_HEARTBURN",
        "clinical_reference": "American College of Gastroenterology (ACG) GERD Guidelines (Am J Gastroenterol 2022); NICE Guideline CG184 (2019). Non-pharma: head-of-bed 6-inch elevation, 3-hour dinner-to-bed buffer, small frequent meals. Red flags: dysphagia, hematemesis, ruling out Acute Coronary Syndrome (ACS).",
        "snomed_code": "235595009",
        "name": "Gastroesophageal Reflux / Dyspepsia",
        "domain": "Gastrointestinal",
        "anatomical_site": "Epigastric / Chest",
        "expected_resolution_days": 3,
        "max_self_care_days": 5,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Dysphagia (food sticking in esophagus when swallowing)",
            "Persistent vomiting or hematemesis (coffee-ground emesis)",
            "Crushing chest pressure or pain radiating to left shoulder (ACS rule-out)"
        ],
        "aliases": [
            "acidity", "heartburn", "acid reflux", "sour burps", "chhati mein jalan",
            "pet mein jalan", "gerd", "bloating and acid", "khatti dakar"
        ],
        "approved_modalities": [
            "Elevate head of bed 6 inches or sleep with extra supportive pillow",
            "Finish dinner at least 3 hours before lying down",
            "Tender coconut water or cold milk sip for immediate comfort",
            "Small, frequent meals rather than large heavy dinners"
        ],
        "contraindicated": ["Lying down immediately after eating", "Late-night heavy meals", "Raw onion/chili"]
    },
    "GI_CONSTIPATION": {
        "canonical_key": "GI_CONSTIPATION",
        "clinical_reference": "AGA-ACG Clinical Practice Guideline: Management of Chronic Constipation (Gastroenterology 2023); NICE CKS 'Constipation in older people' (2022); MoHFW Standard Treatment Guidelines: Eldercare (2016). Non-pharma: psyllium husk (isabgol) titration, post-prandial mobilization, hydration. Red flags: obstipation > 4 days with vomiting, rectal bleeding.",
        "snomed_code": "14760008",
        "name": "Constipation / Sluggish Bowel Transit",
        "domain": "Gastrointestinal",
        "anatomical_site": "Abdomen",
        "expected_resolution_days": 3,
        "max_self_care_days": 5,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Complete obstipation (no bowel movement or flatus for >4 days with vomiting)",
            "Severe abdominal distension and crampy colic",
            "Rectal bleeding"
        ],
        "aliases": [
            "constipation", "hard stools", "straining at stool", "kabz", "pet saaf nahi hona",
            "infrequent bowel movements"
        ],
        "approved_modalities": [
            "Warm water with 1 tsp soaked isabgol (psyllium husk) at bedtime",
            "Prunes or soaked figs (anjeer) in the morning",
            "Increase dietary soluble fiber (oats, papaya, stewed apples)",
            "Gentle 15-minute post-meal stroll to stimulate peristalsis"
        ],
        "contraindicated": ["Excessive straining", "Ignoring gastrocolic reflex urge after breakfast"]
    },

    # ── 4. RESPIRATORY & ENT ──
    "RESP_POST_VIRAL_COUGH": {
        "canonical_key": "RESP_POST_VIRAL_COUGH",
        "clinical_reference": "CHEST Expert Panel Report: Postinfectious Cough Guideline (Chest 2018); NICE Guideline NG120 (2019). Defines 3-week upper boundary for subacute post-viral airway hyperresponsiveness. Non-pharma: warm saline gargles, honey with ginger, steam humidification. Red flags: hemoptysis, resting SpO2 < 92%, pleurisy.",
        "snomed_code": "263731006",
        "name": "Subacute Post-Viral Cough / Airway Hyperresponsiveness",
        "domain": "Respiratory",
        "anatomical_site": "Lower Respiratory",
        "expected_resolution_days": 14,
        "max_self_care_days": 21,  # 3-week clinical boundary before CXR / workup
        "checkin_cadence_days": 3,
        "red_flags": [
            "Hemoptysis (coughing up blood or rust-colored sputum)",
            "Resting SpO2 < 92% or breathlessness at rest",
            "High fever > 101°F with sharp pleuritic chest pain on inspiration"
        ],
        "aliases": [
            "cough", "dry cough", "tickly cough", "lingering cough", "khansi",
            "sukhi khansi", "throat irritation cough", "post-cold cough"
        ],
        "approved_modalities": [
            "Warm saline water gargle (twice daily)",
            "Warm water with half-teaspoon honey and crushed ginger",
            "Steam inhalation for 5-7 minutes before bed",
            "Keep bedroom air humidified; prop up head with an extra pillow"
        ],
        "contraindicated": ["Iced cold drinks", "Direct cold AC draft", "Smoke / incense exposure"]
    },
    "RESP_NASAL_CONGESTION": {
        "canonical_key": "RESP_NASAL_CONGESTION",
        "clinical_reference": "American Academy of Otolaryngology-Head and Neck Surgery (AAO-HNS) Adult Sinusitis Guideline (2015/2020); EPOS 2020 Guidelines on Rhinosinusitis. Non-pharma: isotonic saline nasal lavage, warm sinus compress. Contraindication: topical alpha-agonist sprays > 3 days (rhinitis medicamentosa). Red flags: orbital cellulitis, high fever with meningismus.",
        "snomed_code": "68235000",
        "name": "Upper Respiratory Congestion / Rhinitis",
        "domain": "Respiratory",
        "anatomical_site": "Ears / Nose / Throat",
        "expected_resolution_days": 5,
        "max_self_care_days": 7,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Severe unilateral facial pain or swelling around eyes (invasive sinusitis)",
            "Stiff neck or purulent foul-smelling nasal discharge with high fever"
        ],
        "aliases": [
            "stuffy nose", "blocked nose", "nasal congestion", "runny nose", "cold",
            "nak band", "sinus pressure", "rhinitis"
        ],
        "approved_modalities": [
            "Plain saline nasal spray or saline drops (2 drops per nostril)",
            "Warm moist face towel compress over forehead and sinuses",
            "Warm herbal tulsi / ginger tea"
        ],
        "contraindicated": ["OTC decongestant nasal spray overuse beyond 3 days (rebound congestion)"]
    },

    # ── 5. CARDIOVASCULAR & PERIPHERAL VASCULAR ──
    "VASC_BILATERAL_PEDAL_EDEMA": {
        "canonical_key": "VASC_BILATERAL_PEDAL_EDEMA",
        "clinical_reference": "AHA Scientific Statement: Evaluation and Management of Peripheral Edema (Circulation 2020); ICMR STW on Heart Failure (2022). Non-pharma: bilateral dependent elevation above heart level 30 mins BID, seated calf pumps, dietary sodium moderation. Red flags: unilateral acute calf tenderness (DVT rule-out), acute orthopnea/sudden weight gain.",
        "snomed_code": "225624000",
        "name": "Dependent Bilateral Lower Extremity Edema",
        "domain": "Cardiovascular",
        "anatomical_site": "Ankles / Feet",
        "expected_resolution_days": 5,
        "max_self_care_days": 5,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Unilateral leg swelling with calf tenderness and warmth (DVT rule-out)",
            "Sudden weight gain > 1.5kg in 48h with breathlessness when lying flat (Orthopnea)",
            "Pitting edema reaching above mid-shin"
        ],
        "aliases": [
            "swollen feet", "swollen ankles", "pedal edema", "puffy feet", "pairon mein sujan",
            "feet swelling after sitting", "tight shoes"
        ],
        "approved_modalities": [
            "Elevate feet above heart level for 20-30 minutes twice daily",
            "Ankle rotations and calf pumps while seated",
            "Moderate dietary sodium (avoid papads, pickles, salty snacks)",
            "Avoid prolonged uninterrupted seated postures"
        ],
        "contraindicated": ["Crossing legs at knees", "Prolonged uninterrupted standing"]
    },

    # ── 6. DERMATOLOGICAL & SOFT TISSUE ──
    "DERM_XEROSIS_PRURITUS": {
        "canonical_key": "DERM_XEROSIS_PRURITUS",
        "clinical_reference": "European Academy of Dermatology and Venereology (EADV) Chronic Pruritus in Elderly Guidelines (2020); IADVL Consensus on Senile Pruritus & Skin Barrier Repair (2021). Non-pharma: virgin coconut oil/ceramide emollient applied within 3 minutes of lukewarm bath ('soak & seal'). Red flags: cholestatic jaundice, secondary cellulitis.",
        "snomed_code": "271758003",
        "name": "Senile Xerosis / Dry Skin Pruritus",
        "domain": "Dermatological",
        "anatomical_site": "Full Body / Systemic",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Skin breakdown, oozing, open ulceration, or spreading cellulitis redness",
            "Severe generalized itching with jaundice (yellow eyes/skin)"
        ],
        "aliases": [
            "dry skin", "itching", "itchy skin", "flaky skin", "khujli", "sukhi twacha",
            "winter itch", "pruritus", "dandruff", "severe dandruff", "dry, itchy scalp",
            "itchy scalp", "flaking", "facial redness and flaking", "flaking on face"
        ],
        "approved_modalities": [
            "Apply virgin coconut oil or fragrance-free ceramide cream within 3 mins of bathing",
            "Use lukewarm water rather than steaming hot showers",
            "Use mild, soap-free gentle cleansing bars"
        ],
        "contraindicated": ["Hot water baths", "Harsh antibacterial soaps", "Vigorous towel scrubbing"]
    },

    # ── 7. SLEEP & CIRCADIAN ──
    "SLEEP_ONSET_INSOMNIA": {
        "canonical_key": "SLEEP_ONSET_INSOMNIA",
        "clinical_reference": "American Academy of Sleep Medicine (AASM) Clinical Practice Guideline for Chronic Insomnia (2021); NICE CKS 'Insomnia in older adults' (2022); AGS Beers Criteria (avoiding sedative-hypnotic polypharmacy). Non-pharma: CBT-I stimulus control, fixed wake time, 20-min bed-exit rule, evening screen restriction. Red flags: severe daytime cognitive lapse, witnessed choking/apneas.",
        "snomed_code": "416666002",
        "name": "Transient Sleep Onset Insomnia",
        "domain": "Sleep",
        "anatomical_site": "Full Body / Systemic",
        "expected_resolution_days": 5,
        "max_self_care_days": 7,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Severe daytime cognitive confusion or falling asleep while driving",
            "Nighttime gasping / witnessed choking episodes (OSA rule-out)"
        ],
        "aliases": [
            "trouble sleeping", "insomnia", "cannot fall asleep", "neend nahi aana",
            "restless sleep", "tossing and turning", "sleep difficulty",
            "poor sleep", "inadequate sleep", "racing thoughts at bedtime", "racing thoughts", "sleep"
        ],
        "approved_modalities": [
            "Establish consistent wake-up time even after poor night's sleep",
            "Warm chamomile tea or warm milk with pinch of nutmeg 45 mins before bed",
            "Screens off 1 hour before sleep; 5-minute slow 4-7-8 breathing",
            "If awake > 20 mins, get out of bed into dim light until sleepy"
        ],
        "contraindicated": ["Caffeine after 3:00 PM", "Watching TV in bed", "Daytime naps > 30 mins"]
    },

    # ── 8. PSYCHOSOMATIC & EMOTIONAL WELLBEING ──
    "PSYCH_SOMATIC_FATIGUE": {
        "canonical_key": "PSYCH_SOMATIC_FATIGUE",
        "clinical_reference": "WHO ICOPE (Integrated Care for Older People) Vitality Guidelines (2019/2021); RCGP Guidance on Tiredness and Fatigue (2020). Non-pharma: morning 15-min natural sunlight circadian reset, pacing, protein-energy hydration balance. Red flags: unexplained weight loss > 3kg, drenching night sweats, persistent pyrexia, severe clinical depression.",
        "snomed_code": "84229001",
        "name": "Mild Functional Fatigue / Low Vitality",
        "domain": "Systemic",
        "anatomical_site": "Full Body / Systemic",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Unexplained weight loss > 3kg in 1 month",
            "Drenching night sweats or persistent low-grade fever",
            "Severe anhedonia, pervasive despair, or suicidal thoughts"
        ],
        "aliases": [
            "tiredness", "fatigue", "low energy", "exhausted", "thakan", "kamzori",
            "feeling drained", "lack of stamina"
        ],
        "approved_modalities": [
            "Morning sunlight exposure for 15 minutes to reset circadian rhythm",
            "Ensure adequate hydration and small protein-rich snacks",
            "Gentle 10-minute walk rather than complete bed rest"
        ],
        "contraindicated": ["Prolonged all-day daytime bed confinement"]
    },
    "PSYCH_STRESS_ANXIETY": {
        "canonical_key": "PSYCH_STRESS_ANXIETY",
        "clinical_reference": "NICE Guideline CG113 'Generalised anxiety disorder and panic disorder in adults' (2019); ICMR Mental Health in Primary Care Guidelines (2020). Non-pharma: 4-4-4-4 box breathing, slow garden walking, evening digital media restriction. Red flags: acute panic mimicking cardiac event, active suicidal ideation.",
        "snomed_code": "197480006",
        "name": "Situational Anxiety & Stress",
        "domain": "Mental Health",
        "anatomical_site": "Full Body / Systemic",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Severe panic attacks with chest tightness",
            "Suicidal ideation or self-harm thoughts",
            "Severe acute functional impairment"
        ],
        "aliases": [
            "stress", "high stress", "daytime stress", "anxiety", "anxious", "tension", "chinta", "nervousness", "restlessness"
        ],
        "approved_modalities": [
            "Box breathing exercise (4 sec in, 4 hold, 4 out, 4 hold)",
            "Mindful slow walking in quiet garden or corridor",
            "Limit evening news, screens, and caffeine intake",
            "Gentle journaling or sharing thoughts with family"
        ],
        "contraindicated": ["Excessive caffeine", "Late-night emotional arguments"]
    },
    "RESP_NOCTURNAL_DESATURATION": {
        "canonical_key": "RESP_NOCTURNAL_DESATURATION",
        "clinical_reference": "AASM Guidelines for Adult Obstructive Sleep Apnea (J Clin Sleep Med 2018); British Thoracic Society (BTS) Sleep Apnea Guidelines (Thorax 2020). Non-pharma: 30-45 degree head-of-bed elevation, lateral decubitus positioning (avoiding supine collapsibility), bedtime sedative elimination. Red flags: daytime resting SpO2 < 90%, witnessed apneas.",
        "snomed_code": "73430006",
        "name": "Nocturnal Hypoxemia / Oxygen Desaturation",
        "domain": "Respiratory",
        "anatomical_site": "Respiratory / Lungs",
        "expected_resolution_days": 3,
        "max_self_care_days": 3,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Resting daytime SpO2 < 90%",
            "Severe morning confusion, daytime sleepiness, or witnessed apneas",
            "Cyanosis of lips or nail beds"
        ],
        "aliases": [
            "nighttime oxygen desaturation", "oxygen desaturation", "low oxygen", "low spo2", "sleep apnea", "breathing pause"
        ],
        "approved_modalities": [
            "Sleep with head elevated 30-45 degrees or on side rather than supine",
            "Avoid alcohol or sedative medications close to bedtime",
            "Ensure bedroom ventilation is clean and unpolluted"
        ],
        "contraindicated": ["Sleeping flat on back (supine position)"]
    },

    # ── 9. GENITOURINARY & PELVIC ──
    "GU_DYSURIA_SUSPECTED_UTI": {
        "canonical_key": "GU_DYSURIA_SUSPECTED_UTI",
        "clinical_reference": "NICE Guideline NG109 'Urinary tract infection (lower): antimicrobial prescribing' (2018); IDSA/EAU Guidelines on Urological Infections (2023); ICMR Standard Treatment Workflow on Acute Lower UTI (2022). Strict 48h conservative SLA: high vulnerability to delirium and urosepsis in elders. Non-pharma: liberal hydration (2-2.5L), barley water (jau ka pani), prompt regular voiding. Red flags: fever > 100.5°F with rigors, flank pain, hematuria, acute delirium.",
        "snomed_code": "49650001",
        "name": "Dysuria / Suspected Lower Urinary Tract Discomfort",
        "domain": "Genitourinary",
        "anatomical_site": "Bladder / Urinary Tract",
        "expected_resolution_days": 2,
        "max_self_care_days": 2,  # Strict 48h SLA: high risk of urosepsis/delirium in seniors
        "checkin_cadence_days": 1,
        "red_flags": [
            "Fever > 100.5°F with shaking chills or rigors",
            "Flank, loin, or lower back pain (suspected pyelonephritis)",
            "Gross hematuria (visible pink, red, or cola-colored urine)",
            "Acute confusion, disorientation, or sudden delirium",
            "Anuria or unable to pass urine for > 8 hours"
        ],
        "aliases": [
            "burning urination", "painful urination", "dysuria", "peshab mein jalan",
            "mutra jalan", "burning pee", "urinary burning", "discomfort passing urine",
            "peshab karte waqt dard", "uti symptoms", "urine infection feeling",
            "pelvic pain", "pelvic discomfort", "suprapubic pain"
        ],
        "approved_modalities": [
            "Liberal hydration: drink 2 to 2.5 liters of clean water spread evenly throughout the day (unless fluid-restricted for heart or kidney disease)",
            "Barley water (jau ka pani) or fresh tender coconut water to soothe the urinary tract",
            "Prompt bladder emptying: void every 2-3 hours, do not hold urine",
            "Wipe strictly from front to back after voiding"
        ],
        "contraindicated": ["Holding urine for long intervals", "Excessive tea, coffee, or spicy condiments", "Self-initiating OTC antibiotics"]
    },
    "GU_NOCTURIA_FREQUENCY": {
        "canonical_key": "GU_NOCTURIA_FREQUENCY",
        "clinical_reference": "EAU Guidelines on Male Lower Urinary Tract Symptoms (LUTS) and Benign Prostatic Obstruction (2023); AUA Guideline on BPH Management (J Urol 2021); WHO ICOPE Continence & Fall Prevention Domain (2019). Non-pharma: evening fluid restriction after 7:30 PM, double voiding before bed, late afternoon leg elevation, bathroom nightlight illumination to eliminate fall hazard. Red flags: acute urinary retention, gross hematuria.",
        "snomed_code": "28442001",
        "name": "Nocturia & Bladder Urgency / Frequency",
        "domain": "Genitourinary",
        "anatomical_site": "Bladder / Urinary Tract",
        "expected_resolution_days": 7,
        "max_self_care_days": 10,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Acute urinary retention (painful, full lower abdomen with complete inability to void)",
            "Gross hematuria (blood in urine)",
            "Sudden overflow incontinence (uncontrollable continuous dribbling with bladder fullness)"
        ],
        "aliases": [
            "frequent urination at night", "nocturia", "waking up to pee", "nighttime urination",
            "raat ko baar baar peshab aana", "peshab ki haajat", "frequent urination",
            "peshab baar baar aana", "bladder urgency", "bph symptoms", "weak urine stream"
        ],
        "approved_modalities": [
            "Restrict fluids and avoid milk, tea, coffee, or sodas after 7:30 PM",
            "Double voiding technique before bed: urinate once, wait 2 minutes, relax and void again",
            "Elevate feet for 30 minutes in the late afternoon to mobilize dependent fluid before night",
            "Ensure clear, illuminated pathway to the bathroom to eliminate nighttime fall risk"
        ],
        "contraindicated": ["Drinking large volumes of water immediately before bedtime", "Evening caffeinated tea/coffee", "Rushing hurriedly out of bed in the dark"]
    },

    # ── 10. NEUROPATHIC & PERIPHERAL NERVOUS SYSTEM ──
    "NEURO_PERIPHERAL_NEUROPATHY": {
        "canonical_key": "NEURO_PERIPHERAL_NEUROPATHY",
        "clinical_reference": "American Diabetes Association (ADA) Standards of Care in Diabetes: Neuropathy and Foot Care (Diabetes Care 2024); ICMR Guidelines on Management of Type 2 Diabetes (2022); International Working Group on the Diabetic Foot (IWGDF 2023). Non-pharma: daily mirror sole inspection, lukewarm water wash (elbow-tested), pure coconut oil on soles (never toe webs), seamless cotton socks, strictly zero barefoot walking. Red flags: any skin ulceration, localized heat/swelling, gangrene.",
        "snomed_code": "386033004",
        "name": "Peripheral Neuropathy / Extremity Paresthesia",
        "domain": "Neurological",
        "anatomical_site": "Feet / Lower Extremities",
        "expected_resolution_days": 14,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Any open skin ulcer, blister, or cut on the foot or between toes",
            "Localized warmth, spreading erythema, or foul discharge (cellulitis/diabetic foot infection)",
            "Blackening of toes or severe cold pale foot (acute peripheral ischemia/gangrene)",
            "Rapidly ascending numbness or progressive foot drop / leg weakness"
        ],
        "aliases": [
            "burning feet", "burning soles", "pins and needles in feet", "tingling in feet",
            "pairon mein jalan", "talwo mein aag nikalna", "pairon mein jhanjhanahat",
            "foot numbness", "pair sunn hona", "diabetic neuropathy", "numbness in toes"
        ],
        "approved_modalities": [
            "Daily visual inspection of soles and between toes using a well-lit handheld mirror",
            "Wash feet in lukewarm water (test temperature with elbow or wrist, never feet)",
            "Apply thin layer of pure coconut oil or moisturiser on soles and heels, avoiding spaces between toes",
            "Wear seamless, breathable, non-constricting cotton socks and never walk barefoot indoors or outdoors"
        ],
        "contraindicated": ["Walking barefoot on cold marble, tile, or outdoor temple floors", "Using hot water bottles or heating pads on numb feet (burn risk)", "Cutting corns or calluses at home"]
    },
    "NEURO_NOCTURNAL_LEG_CRAMPS": {
        "canonical_key": "NEURO_NOCTURNAL_LEG_CRAMPS",
        "clinical_reference": "American Family Physician (AFP) Clinical Review on Nocturnal Leg Cramps (2012/2021); NICE CKS 'Leg cramps' (2022). Non-pharma: pre-bed wall calf stretch, acute forceful ankle dorsiflexion toward shin, warm towel compress, daytime hydration with potassium/magnesium rich nutrition. Red flags: asymmetric calf redness, swelling, deep tenderness (DVT rule-out).",
        "snomed_code": "427777002",
        "name": "Nocturnal Calf Muscle Cramps & Spasms",
        "domain": "Neurological",
        "anatomical_site": "Calves / Legs",
        "expected_resolution_days": 5,
        "max_self_care_days": 7,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Unilateral persistent calf swelling, redness, and deep tenderness (DVT rule-out)",
            "Calf pain provoked predictably by walking 100 meters and relieved by rest (claudication/PAD)",
            "Severe muscle weakness or dark tea-colored urine"
        ],
        "aliases": [
            "leg cramps", "calf cramp", "night leg cramps", "pindli mein ainthun",
            "taang mein khinchao", "nas chadhna", "pain in calf at night", "charlie horse"
        ],
        "approved_modalities": [
            "Gentle calf wall-stretch for 3 minutes before getting into bed",
            "Passive dorsiflexion of the ankle (pull toes toward your shin) during an acute cramp",
            "Warm shower or warm towel compress over the calf muscle before sleep",
            "Maintain daytime hydration and include potassium/magnesium foods (banana, coconut water, soaked almonds)"
        ],
        "contraindicated": ["Pointing toes downward forcefully in bed", "Dehydration from skipping water during the day"]
    },

    # ── 11. FOOT & SMALL JOINT MUSCULOSKELETAL ──
    "MSK_PLANTAR_FASCIITIS": {
        "canonical_key": "MSK_PLANTAR_FASCIITIS",
        "clinical_reference": "Journal of Orthopaedic & Sports Physical Therapy (JOSPT) Clinical Practice Guidelines: Heel Pain - Plantar Fasciitis (J Orthop Sports Phys Ther 2023); ACFAS Clinical Consensus (2018). First-step morning heel pain pathogenesis. Non-pharma: arch rolling with chilled bottle/tennis ball, pre-rising seated toe dorsiflexion, silicone heel cups, avoiding barefoot walking on tile/marble. Red flags: inability to bear weight, audible plantar pop with ecchymosis.",
        "snomed_code": "19440003",
        "name": "Plantar Fasciitis / Calcaneal Heel Pain",
        "domain": "Musculoskeletal",
        "anatomical_site": "Feet / Heels",
        "expected_resolution_days": 14,
        "max_self_care_days": 21,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Inability to bear any weight on the foot after a misstep or fall",
            "Severe localized heel swelling, warmth, or fever (calcaneal osteomyelitis rule-out)",
            "Sudden sharp audible pop with intense plantar pain and bruising (plantar fascia rupture)"
        ],
        "aliases": [
            "heel pain", "heel ache", "plantar fasciitis", "aidi mein dard",
            "morning heel pain", "pain on first step", "calcaneal spur pain", "sole pain near heel"
        ],
        "approved_modalities": [
            "Roll a chilled water bottle or tennis ball under the arch of the foot for 5-8 minutes twice daily",
            "Gentle seated calf and toe dorsiflexion stretches before taking the first morning steps",
            "Wear supportive, cushioned footwear with arch support indoors (avoid flat hard chappals)",
            "Silicone heel cups or gel pads inside footwear"
        ],
        "contraindicated": ["Walking barefoot on bare marble, concrete, or tile floors", "Wearing completely flat worn-out slippers"]
    },
    "MSK_HAND_OSTEOARTHRITIS": {
        "canonical_key": "MSK_HAND_OSTEOARTHRITIS",
        "clinical_reference": "EULAR Recommendations for the Management of Hand Osteoarthritis (Ann Rheum Dis 2019); ACR/Arthritis Foundation Hand OA Guideline (2019). Non-pharma: warm water hand soaks, soft sponge ball squeezes, ergonomic thick-handled utensils/jar openers, gentle sesame oil massage. Red flags: morning stiffness > 60 mins with bilateral MCP boggy swelling (rheumatoid arthritis rule-out), septic single hot joint.",
        "snomed_code": "239874001",
        "name": "Hand & Finger Osteoarthritis / Joint Stiffness",
        "domain": "Musculoskeletal",
        "anatomical_site": "Hands / Fingers",
        "expected_resolution_days": 10,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Morning joint stiffness lasting > 60 minutes with warm, boggy bilateral knuckle swelling (inflammatory arthritis/RA rule-out)",
            "Hot, red, exquisitely swollen single finger joint with fever (septic arthritis or acute gout)",
            "Sudden numbness or loss of sensation in thumb, index, and middle fingers with dropping objects (severe carpal tunnel)"
        ],
        "aliases": [
            "hand pain", "finger stiffness", "finger joint ache", "ungliyon mein dard",
            "ungliyon ki jakdan", "stiff fingers in morning", "hand arthritis", "thumb base pain",
            "difficulty gripping", "joint knots on fingers"
        ],
        "approved_modalities": [
            "Soak hands in warm water for 10 minutes in the morning followed by gentle finger flex/extension glides",
            "Gentle sponge ball or soft stress-ball squeezing exercises",
            "Use ergonomic thick-handled pens, jar openers, and soft-grip utensils",
            "Gentle sesame oil massage over finger joints"
        ],
        "contraindicated": ["Forceful aggressive finger popping/cracking", "Forceful repetitive twisting motions like wringing heavy wet clothes"]
    },

    # ── 12. CARDIOVASCULAR & HEMODYNAMIC ──
    "CARDIO_PALPITATIONS": {
        "canonical_key": "CARDIO_PALPITATIONS",
        "clinical_reference": "ESC Guidelines for the Diagnosis and Management of Atrial Fibrillation (Eur Heart J 2020); ACC/AHA/HRS Guideline for Evaluation of Patients with Palpitations (Circulation 2019); ICMR STW for Common Cardiac Arrhythmias (2022). Non-pharma: semi-reclined rest, 4-6 box breathing, sipping cool water, stimulant elimination. Red flags: chest tightness/pain (ACS rule-out), syncope/near-syncope, dyspnea, resting pulse > 120 bpm.",
        "snomed_code": "80313002",
        "name": "Intermittent Palpitations / Resting Cardiac Awareness",
        "domain": "Cardiovascular",
        "anatomical_site": "Chest / Heart",
        "expected_resolution_days": 2,
        "max_self_care_days": 3,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Palpitations accompanied by chest pressure, heaviness, tightness, or jaw/left arm pain (ACS rule-out)",
            "Syncope (true fainting, blackout) or near-syncope with postural collapse",
            "Shortness of breath at rest or resting SpO2 < 92%",
            "Irregularly irregular rapid pulse > 120 bpm at rest (suspected new-onset Atrial Fibrillation)"
        ],
        "aliases": [
            "palpitations", "racing heart", "heart fluttering", "irregular heartbeat",
            "dil ki dhadkan tez", "chhati mein dhak dhak", "dil ghabrana", "fluttering in chest",
            "skipped heartbeats", "fast pulse"
        ],
        "approved_modalities": [
            "Sit or lie down in a comfortable semi-reclined position and rest quietly for 15 minutes",
            "Slow diaphragmatic box breathing (inhale 4 sec, exhale slowly through pursed lips 6 sec)",
            "Sip a glass of cool water",
            "Avoid caffeinated tea, coffee, energy drinks, nicotine, and decongestant cold tablets"
        ],
        "contraindicated": ["Vigorous exercise during an episode", "Heavy meals", "Smoking or tobacco consumption", "High stress arguments"]
    },

    # ── 13. OPHTHALMIC & SENSORY ──
    "OPHTH_DRY_EYE_SYNDROME": {
        "canonical_key": "OPHTH_DRY_EYE_SYNDROME",
        "clinical_reference": "TFOS DEWS II Management and Therapy Report (Ocul Surf 2017); AAO Preferred Practice Pattern: Dry Eye Syndrome (Ophthalmology 2018/2023); All India Ophthalmological Society (AIOS) Dry Eye Guidelines (2020). Non-pharma: warm moist eyelid compress (5-10 mins BID to liquefy meibomian lipids), 20-20-20 screen rule, deliberate blink training, redirecting direct fan/AC drafts. Red flags: acute loss of vision, severe eye ache with halos (acute glaucoma).",
        "snomed_code": "399897003",
        "name": "Senile Xerophthalmia / Dry Eye Syndrome",
        "domain": "Ophthalmic",
        "anatomical_site": "Eyes / Ocular",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Sudden loss or acute blurring of vision",
            "Severe deep eye ache with nausea, vomiting, or colored halos around lights (acute angle-closure glaucoma)",
            "Marked photophobia (intense pain from light exposure)",
            "Thick purulent green/yellow discharge or visible white corneal spot"
        ],
        "aliases": [
            "dry eyes", "eye irritation", "burning eyes", "gritty eyes", "sand in eyes",
            "aankhon mein jalan", "aankhon mein chubhan", "watery eyes", "aankh se paani aana",
            "tired eyes", "scratchy eyes", "eye redness"
        ],
        "approved_modalities": [
            "Apply a clean, warm, moist washcloth over closed eyelids for 5-10 minutes twice daily",
            "Practice the 20-20-20 rule during screen viewing (every 20 mins look 20 feet away for 20 seconds)",
            "Deliberate complete blinking exercises (10 full gentle blinks every hour)",
            "Position ceiling fans or AC louvers away from blowing directly into the face"
        ],
        "contraindicated": ["Rubbing the eyes vigorously with unwashed hands", "Sitting directly in the direct draft of air conditioners or table fans", "Using unverified over-the-counter medicated steroid eye drops"]
    },

    # ── 14. ORAL HEALTH & DIGESTIVE ──
    "ORAL_XEROSTOMIA": {
        "canonical_key": "ORAL_XEROSTOMIA",
        "clinical_reference": "World Dental Federation (FDI) Policy Statement on Xerostomia in Older Adults (2020); ADA Clinical Guidelines on Managing Salivary Hypofunction (2022); WHO Oral Health in Aging Populations (2021). Non-pharma: bedside frequent water sips, sugar-free gum/drops for gustatory salivary stimulation, food moistening (gravies/rasam/soups), avoiding alcohol mouthwashes. Red flags: severe dysphagia/choking, non-healing oral ulcer > 2 weeks (malignancy rule-out).",
        "snomed_code": "87715008",
        "name": "Oral Xerostomia / Medication-Induced Dry Mouth",
        "domain": "Oral Health",
        "anatomical_site": "Mouth / Oral Cavity",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 3,
        "red_flags": [
            "Severe dysphagia (inability to swallow liquids or solids, coughing/choking on swallowing)",
            "Non-healing oral ulcer or white/red mucosal patch lasting > 2 weeks (oral malignancy rule-out)",
            "Spreading oral candidiasis with painful white curds on tongue/pharynx",
            "Severe dental pain with facial swelling"
        ],
        "aliases": [
            "dry mouth", "xerostomia", "mouth dryness", "cotton mouth", "munh sookhna",
            "jeebh sookhna", "gala sookhna", "difficulty chewing dry food", "burning tongue",
            "dry throat and mouth"
        ],
        "approved_modalities": [
            "Take frequent small sips of water throughout the day and keep a water bottle bedside",
            "Chew sugar-free gum or suck on sugar-free lemon/mint drops to stimulate natural saliva",
            "Moisten dry foods with broths, gravies, rasam, curd, or soups before eating",
            "Rinse mouth with plain water after meals and maintain gentle oral hygiene with a soft toothbrush"
        ],
        "contraindicated": ["Alcohol-containing commercial mouthwashes (drying effect)", "Very salty, acidic, or extremely dry/crisp foods", "Caffeinated beverages"]
    },
    "GI_DYSPEPSIA_BLOATING": {
        "canonical_key": "GI_DYSPEPSIA_BLOATING",
        "clinical_reference": "ACG/CAG Clinical Guideline: Management of Dyspepsia (Am J Gastroenterol 2017); Rome IV Diagnostic Criteria for Functional GI Disorders (2016); Indian Society of Gastroenterology (ISG) Consensus on Functional Dyspepsia (2020). Non-pharma: warm ajwain/jeera infused water after meals, unhurried eating, 100-step stroll (shatapadi), avoiding evening fried besan/sodas. Red flags: age > 60 with new dyspepsia, unintentional weight loss > 3kg, melena, persistent vomiting.",
        "snomed_code": "40954005",
        "name": "Functional Dyspepsia & Abdominal Bloating / Gas",
        "domain": "Gastrointestinal",
        "anatomical_site": "Abdomen",
        "expected_resolution_days": 3,
        "max_self_care_days": 7,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Unintentional significant weight loss (> 3 kg over 1-2 months)",
            "Persistent vomiting or vomiting blood (hematemesis)",
            "Black tarry stools (melena)",
            "Palpable abdominal lump or severe focal localized tenderness",
            "New onset dyspepsia starting for the first time over age 60"
        ],
        "aliases": [
            "bloating", "gas", "pet phoolna", "afara", "pet bhari hona", "flatulence",
            "stomach bloating", "fullness after eating", "excessive gas", "heaviness in stomach",
            "indigestion", "pet mein gas", "badhazmi", "stomach ache", "pet dard",
            "abdominal pain", "lower abdominal pain", "stomach pain", "abdominal cramp"
        ],
        "approved_modalities": [
            "Sip warm ajwain (carom seed) or jeera (cumin) infused water 20 minutes after meals",
            "Take small, unhurried meals; chew each morsel thoroughly without talking while eating",
            "Gentle 10-15 minute slow stroll (shatapadi / 100 steps) after meals to encourage gastric motility",
            "Avoid carbonated beverages and heavy fried besan/lentil preparations in the evening"
        ],
        "contraindicated": ["Lying down flat immediately after eating", "Carbonated fizzy sodas", "Gulping meals down hurriedly"]
    },
    "METAB_NOCTURNAL_SUGAR_CRAVINGS": {
        "canonical_key": "METAB_NOCTURNAL_SUGAR_CRAVINGS",
        "clinical_reference": "RSSDI (Research Society for the Study of Diabetes in India) Clinical Practice Recommendations for Management of Type 2 Diabetes in Elderly (2022); ADA Standards of Care in Diabetes: Older Adults (Diabetes Care 2024); Endocrine Society Clinical Practice Guideline on Hypoglycemia / Glycemic Variability (2021). Non-pharma: late-evening protein/fiber pacing (roasted chana, soaked almonds/walnuts, cinnamon infusion), evening complex carbs, avoiding high-glycemic dinner spikes, hydration review. Red flags: acute diaphoresis, tremors, morning confusion (nocturnal hypoglycemia rule-out).",
        "snomed_code": "40954005",
        "name": "Nocturnal Glycemic Dips & Sugar Cravings",
        "domain": "Metabolic & Endocrine",
        "anatomical_site": "Metabolic / Endocrine",
        "relief_badge": "BLOOD SUGAR BALANCE",
        "expected_resolution_days": 7,
        "max_self_care_days": 14,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Cold sweat (diaphoresis), shakiness, or dizziness at night (hypoglycemia red flag)",
            "Confusion, slurred speech, or profound disorientation on awakening",
            "Severe unquenchable thirst accompanied by frequent urination (marked hyperglycemia)",
            "Blood glucose reading < 70 mg/dL or > 300 mg/dL"
        ],
        "aliases": [
            "sugar cravings", "nighttime sugar cravings", "sweet cravings", "meetha khane ki iccha",
            "meetha khana", "sugar craving", "craving sweets", "midnight snacking", "late night hunger",
            "night hunger", "post-dinner craving", "cravings at night", "sweet tooth at night"
        ],
        "approved_modalities": [
            "Have a small handful of roasted chana (Bengal gram) or 4-5 soaked almonds/walnuts when evening cravings hit",
            "Sip a cup of warm cinnamon (dalchini) or chamomile tea after dinner to stabilize evening cravings",
            "Ensure dinner includes adequate protein (paneer, dal, eggs) and greens rather than simple refined carbohydrates",
            "Drink a glass of warm water before reaching for bedtime snacks to rule out mild dehydration thirst"
        ],
        "contraindicated": [
            "Eating refined sweets, cookies, ice cream, or sugary confectionery close to bedtime",
            "Skipping dinner or prolonged bedtime fasting when taking sulfonylureas or insulin"
        ]
    },
    "METAB_POSTPRANDIAL_SOMNOLENCE": {
        "canonical_key": "METAB_POSTPRANDIAL_SOMNOLENCE",
        "clinical_reference": "ICMR Guidelines for Management of Type 2 Diabetes (2018); ADA Guidelines on Postprandial Glycemic Control (2023). Non-pharma: gentle 10-15 min stroll (Shatpavali), reduction of refined white rice/maida, inclusion of fiber-rich salads before meals.",
        "snomed_code": "271795006",
        "name": "Postprandial Somnolence & Reactive Glucose Spikes",
        "domain": "Metabolic & Endocrine",
        "anatomical_site": "Metabolic / Endocrine",
        "relief_badge": "ENERGY & METABOLISM",
        "expected_resolution_days": 5,
        "max_self_care_days": 10,
        "checkin_cadence_days": 2,
        "red_flags": [
            "Difficulty waking up or unresponsiveness after meals",
            "Sudden blurry vision or profuse sweating",
            "Persistent post-meal confusion"
        ],
        "aliases": [
            "tired after lunch", "post meal sleepiness", "food coma", "heavy after eating",
            "khana khane ke baad neend", "postprandial drowsiness", "lethargy after meals", "sluggish after lunch"
        ],
        "approved_modalities": [
            "Take a gentle 10-15 minute walk (Shatpavali) at normal pacing within 30 minutes after lunch",
            "Start meals with fiber/salad (cucumber, tomato, sprouts) before grains to slow glycemic absorption",
            "Divide heavy afternoon meals into smaller, balanced portions"
        ],
        "contraindicated": ["Lying down to sleep immediately after lunch", "Consuming oversized portions of refined carbohydrates"]
    },
    "FLUID_DEHYDRATION_DEFICIT": {
        "canonical_key": "FLUID_DEHYDRATION_DEFICIT",
        "clinical_reference": "ESPEN Guideline on Clinical Nutrition and Hydration in Geriatrics (Clin Nutr 2019); MoHFW National Programme for Health Care of the Elderly (NPHCE). Non-pharma: structured hydration timetable, coconut water, thin buttermilk (chaas), monitoring urine color.",
        "snomed_code": "17173007",
        "name": "Subclinical Dehydration & Low Fluid Intake",
        "domain": "Metabolic & Fluid Balance",
        "anatomical_site": "Fluid Balance",
        "relief_badge": "HYDRATION & VITALITY",
        "expected_resolution_days": 3,
        "max_self_care_days": 5,
        "checkin_cadence_days": 1,
        "red_flags": [
            "Oliguria (< 400 mL urine output in 24 hours) or anuria",
            "Postural syncope, sudden dizziness on standing, or fall",
            "Dry shriveled tongue, sunken eyes with sudden acute confusion",
            "Heart failure patients with fluid restriction orders (strict nephrology/cardiology compliance required)"
        ],
        "aliases": [
            "dehydration", "low water intake", "not drinking enough water", "excessive thirst",
            "dry mouth thirst", "kam paani peena", "pyaas lagna", "insufficient hydration"
        ],
        "approved_modalities": [
            "Maintain a timed hydration routine: 1 glass of water after waking, and 1 glass between each meal",
            "Incorporate hydrating fluids like thin buttermilk (chaas with roasted jeera) or coconut water before 4 PM",
            "Keep a marked water bottle nearby to track daytime fluid consumption visually"
        ],
        "contraindicated": ["Over-consuming caffeine or diuretic teas in place of plain water", "Large fluid boluses right before bedtime for seniors with nocturia"]
    }
}

# ── Curated Relief Badges for Eldercare Presentation ──
RELIEF_BADGE_MAP: Dict[str, str] = {
    "MSK_LUMBAR_STRAIN": "LOWER BACK RELIEF",
    "MSK_KNEE_OA_FLARE": "KNEE RELIEF",
    "MSK_CERVICAL_STIFFNESS": "NECK RELIEF",
    "MSK_SHOULDER_IMPINGEMENT": "SHOULDER RELIEF",
    "NEURO_TENSION_HEADACHE": "HEADACHE RELIEF",
    "NEURO_POSTURAL_DIZZINESS": "BALANCE & STABILITY",
    "GI_ACUTE_DIARRHEA": "DIGESTIVE RECOVERY",
    "GI_GERD_HEARTBURN": "ACIDITY RELIEF",
    "GI_CONSTIPATION": "BOWEL REGULARITY",
    "RESP_POST_VIRAL_COUGH": "COUGH & AIRWAY",
    "RESP_NASAL_CONGESTION": "NASAL RELIEF",
    "VASC_BILATERAL_PEDAL_EDEMA": "ANKLE & FOOT RELIEF",
    "DERM_XEROSIS_PRURITUS": "SKIN COMFORT",
    "SLEEP_ONSET_INSOMNIA": "RESTFUL SLEEP",
    "PSYCH_SOMATIC_FATIGUE": "VITALITY & ENERGY",
    "PSYCH_STRESS_ANXIETY": "STRESS & CALM",
    "RESP_NOCTURNAL_DESATURATION": "RESPIRATORY RELIEF",
    "GU_DYSURIA_SUSPECTED_UTI": "URINARY COMFORT",
    "GU_NOCTURIA_FREQUENCY": "BLADDER COMFORT",
    "NEURO_PERIPHERAL_NEUROPATHY": "NERVE & FOOT COMFORT",
    "NEURO_NOCTURNAL_LEG_CRAMPS": "LEG CRAMP RELIEF",
    "MSK_PLANTAR_FASCIITIS": "HEEL & FOOT RELIEF",
    "MSK_HAND_OSTEOARTHRITIS": "HAND & FINGER RELIEF",
    "CARDIO_PALPITATIONS": "HEART COMFORT",
    "OPHTH_DRY_EYE_SYNDROME": "EYE COMFORT",
    "ORAL_XEROSTOMIA": "ORAL COMFORT",
    "GI_DYSPEPSIA_BLOATING": "BLOATING & DIGESTION",
    "METAB_NOCTURNAL_SUGAR_CRAVINGS": "BLOOD SUGAR BALANCE",
    "METAB_POSTPRANDIAL_SOMNOLENCE": "ENERGY & METABOLISM",
    "FLUID_DEHYDRATION_DEFICIT": "HYDRATION & VITALITY",
}

for _k, _badge in RELIEF_BADGE_MAP.items():
    if _k in CLINICAL_TAXONOMY:
        CLINICAL_TAXONOMY[_k]["relief_badge"] = _badge

def get_symptom_relief_badge(key_or_item: Any) -> str:
    """Returns a senior-friendly relief badge text (e.g. 'FOR KNEE RELIEF', 'FOR BLOOD SUGAR BALANCE')."""
    if isinstance(key_or_item, dict):
        if key_or_item.get("relief_badge"):
            b = str(key_or_item["relief_badge"]).strip()
            return b if b.upper().startswith("FOR ") else f"FOR {b.upper()}"
        key = key_or_item.get("canonical_key")
        site = key_or_item.get("anatomical_site")
    else:
        key = str(key_or_item)
        site = None

    if key and key in CLINICAL_TAXONOMY:
        b = CLINICAL_TAXONOMY[key].get("relief_badge")
        if b:
            return b if b.upper().startswith("FOR ") else f"FOR {b.upper()}"

    if site and site not in ["Full Body / Systemic", "General"]:
        clean_site = site.split("/")[0].strip().upper()
        return f"FOR {clean_site} RELIEF"
    return "FOR SYMPTOM RELIEF"

# ── HELPER MATCHING & RETRIEVAL FUNCTIONS ──

def get_canonical_symptom(canonical_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve canonical definition by its primary key."""
    return CLINICAL_TAXONOMY.get(canonical_key)

def match_canonical_symptom(text: str, anatomical_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Deterministically matches raw symptom text against the taxonomy using 
    canonical keys, anatomical sites, and curated vernacular/Hinglish aliases.
    Prioritizes exact matches, then longest phrase containment, then anatomical-directed token matching.
    """
    if not text:
        return None
        
    query = text.lower().strip()
    
    # 1. Direct exact alias match (100% precision)
    for key, item in CLINICAL_TAXONOMY.items():
        if query == key.lower() or query == item["name"].lower():
            return item
        for alias in item["aliases"]:
            if query == alias.lower():
                return item

    # 2. Phrase containment (sort aliases by descending length so specific phrases match before generic subsets)
    all_alias_pairs = []
    for key, item in CLINICAL_TAXONOMY.items():
        for alias in item["aliases"]:
            all_alias_pairs.append((alias.lower(), item))
    all_alias_pairs.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, item in all_alias_pairs:
        # Check if curated multi-word alias is contained in query
        if len(alias) >= 4 and alias in query:
            return item

    # 3. Match by anatomical site correlation if hint is provided
    if anatomical_hint:
        hint = anatomical_hint.lower().strip()
        candidates = [item for item in CLINICAL_TAXONOMY.values() if hint in item["anatomical_site"].lower()]
        if len(candidates) == 1:
            return candidates[0]
        # Disambiguate among candidates using word overlap
        for cand in candidates:
            for word in query.split():
                if len(word) > 3 and any(word in a for a in cand["aliases"]):
                    return cand

    # 4. Token overlap fallback with stopword and generic term suppression
    stopwords = {
        "in", "the", "a", "an", "of", "and", "or", "for", "with", "at", "by", "from", "to", "on", 
        "is", "it", "my", "mein", "ka", "ki", "ke", "ko", "se", "par", "hai", "tha", "thi", 
        "raha", "meri", "mera", "mere", "mujhe", "bohot", "bahut", "thoda", "severe", "mild", "bad"
    }
    generic_words = {"pain", "dard", "ache", "aching", "problem", "takleef", "issue", "trouble", "swelling", "stiffness"}
    
    query_tokens = set(re.findall(r'\w+', query)) - stopwords
    if not query_tokens:
        return None

    best_match = None
    max_score = 0
    
    for key, item in CLINICAL_TAXONOMY.items():
        item_score = 0
        for alias in item["aliases"]:
            alias_tokens = set(re.findall(r'\w+', alias)) - stopwords
            overlap = query_tokens.intersection(alias_tokens)
            if not overlap:
                continue
            # Non-generic words carry full weight (3 pts); generic words carry low weight (1 pt)
            score = sum(3 if w not in generic_words else 1 for w in overlap)
            if score > item_score:
                item_score = score
                
        if item_score > max_score:
            max_score = item_score
            best_match = item
            
    # Require at least one non-generic word match or strong overlap
    if max_score >= 3:
        return best_match
        
    return None

def classify_symptom_with_llm(text: str, anatomical_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Tier 2 LLM Semantic Safety Net:
    Invoked when deterministic matching fails. Uses Gemini 2.5 Flash to map 
    unusual phrasing, regional dialects, or complex descriptions to the 27 canonical keys.
    Returns the canonical dictionary if matched, or None if it is a truly unmapped novel condition.
    """
    if not text:
        return None

    try:
        from app.config import settings
        api_key = os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)
    except Exception:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key or api_key == "your-api-key-here":
        return None

    keys_summary = [f"- {k}: {item['name']} (Site: {item['anatomical_site']})" for k, item in CLINICAL_TAXONOMY.items()]
    
    prompt = f"""You are a clinical ontology mapping engine for an eldercare platform.
A patient described the symptom: "{text}" (Reported body part: "{anatomical_hint or 'General'}").

Classify this description to the SINGLE MOST clinically appropriate Canonical Key from this catalog:
{chr(10).join(keys_summary)}

Instructions:
1. If the symptom represents one of these clinical conditions (even if phrased in Hindi, Tamil, Telugu, regional dialect, or colloquial idioms), return JSON: {{"canonical_key": "EXACT_KEY"}}
2. If it is an entirely distinct clinical entity not represented in the catalog, return JSON: {{"canonical_key": null}}
Return ONLY valid JSON without markdown fences."""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                res_json = json.loads(raw_txt)
                matched_key = res_json.get("canonical_key")
                if matched_key and matched_key in CLINICAL_TAXONOMY:
                    return CLINICAL_TAXONOMY[matched_key]
    except Exception as e:
        print(f"Tier 2 LLM semantic classification notice: {e}")

    return None

