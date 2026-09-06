import re

science_dict = {
    "PreDiabetesProgressionRule": "HbA1c measures the percentage of hemoglobin coated with glucose over a 3-month lifespan of red blood cells. Rising levels indicate a progressive inability of pancreatic beta-cells to clear postprandial and fasting glucose, hallmark signs of insulin resistance leading to type 2 diabetes.",
    "KidneyDeclineRule": "eGFR estimates the volume of fluid filtered from the kidney glomerular capillaries into Bowman's capsule per unit time. A declining eGFR signifies irreversible nephron loss or structural damage (sclerosis) within the kidneys, impairing their ability to filter metabolic waste.",
    "AnemiaDetectionRule": "Hemoglobin is the iron-containing oxygen-transport metalloprotein in red blood cells. A decrease in hemoglobin directly reduces the oxygen-carrying capacity of the blood, leading to tissue hypoxia and compensatory cardiac output increases (tachycardia).",
    "ThyroidDysfunctionRule": "TSH (Thyroid Stimulating Hormone) is secreted by the anterior pituitary to regulate thyroid hormone (T4/T3) production. Through a negative feedback loop, high TSH indicates a failing thyroid gland (hypothyroidism) while low TSH indicates autonomous overproduction by the thyroid (hyperthyroidism).",
    "CardiovascularRiskRule": "LDL cholesterol lipoproteins penetrate the arterial intima where they become oxidized. Macrophages engulf oxidized LDL, becoming foam cells, which triggers an inflammatory cascade resulting in atherosclerotic plaque formation and eventual cardiovascular events.",
    "SilentInsulinResistanceRule": "Hyperinsulinemia occurs as a compensatory mechanism when peripheral tissues (muscle, adipose) become resistant to insulin action. The pancreas secretes excessive insulin to maintain normoglycemia, which can be quantified via the HOMA-IR model before glucose levels ever rise.",
    "AnemiaRootCauseTriageRule": "The Mean Corpuscular Volume (MCV) reflects red blood cell size. Iron deficiency limits hemoglobin synthesis, leading to smaller cells (microcytic), whereas B12/Folate deficiency impairs DNA synthesis, causing arrested cell division and abnormally large cells (macrocytic).",
    "AcuteInfectionRule": "CRP is an acute-phase reactant synthesized by the liver in response to IL-6 released by macrophages during inflammation. The ESR measures how quickly RBCs settle, which increases when acute-phase proteins (like fibrinogen) neutralize RBC surface charge during systemic infection.",
    "MetabolicSyndromeRule": "Metabolic syndrome is driven by visceral adiposity, which releases free fatty acids and inflammatory cytokines. This causes hepatic insulin resistance (driving up triglycerides) and alters lipid metabolism (driving down HDL), significantly multiplying cardiovascular and metabolic risk.",
    "DehydrationAkiRule": "BUN represents urea, a waste product reabsorbed by the kidneys alongside sodium and water during states of volume depletion (dehydration). Creatinine is actively secreted. A disproportionate rise in BUN compared to Creatinine (>20:1 ratio) is the classic physiological hallmark of pre-renal acute kidney injury.",
    "GoutFlareRule": "Uric acid is the end product of purine metabolism. When serum uric acid exceeds its solubility limit (~6.8 mg/dL), it crystallizes as monosodium urate in the synovial fluid of joints, triggering a fierce neutrophil-mediated inflammatory response known as a gout flare.",
    "SevereVitaminDRule": "Vitamin D (25-OH) is converted to its active form in the kidneys to facilitate intestinal calcium absorption. Severe deficiency leads to secondary hyperparathyroidism, where the body leaches calcium from bones to maintain serum levels, resulting in osteomalacia and severe immune dysfunction.",
    "MealTimeGlucoseSpikeRule": "Post-prandial glucose excursions occur when the first-phase insulin response from the pancreas is lost or delayed. High glucose spikes damage endothelial cells via oxidative stress and advanced glycation end-products (AGEs), severely increasing cardiovascular risk.",
    "PulmonaryEmbolismRule": "D-Dimer is a fibrin degradation product present in the blood after a blood clot is degraded by fibrinolysis. An elevated D-Dimer alongside hypoxemia and tachycardia suggests an acute pulmonary embolism, where a clot obstructs the pulmonary vasculature, causing severe right heart strain.",
    "ArrhythmiaElectrolyteRule": "Potassium strictly regulates the resting membrane potential of cardiomyocytes. Hypokalemia prolongs the action potential duration, leading to early afterdepolarizations and fatal arrhythmias like Torsades de Pointes. Hyperkalemia decreases myocardial excitability, risking asystole.",
    "AcuteLiverInjuryRule": "ALT and AST are intracellular liver enzymes. ALT is highly specific to the cytosol of hepatocytes, while AST is found in mitochondria. When hepatocytes are damaged by toxins, ischemia, or viral attack, their cell membranes rupture, spilling these transaminases into the bloodstream.",
    "BiliaryObstructionRule": "ALP is an enzyme concentrated in the biliary canalicular membrane. When bile ducts are obstructed (gallstones, tumors), bile salts accumulate and act as detergents, solubilizing the membrane and causing massive ALP release. GGT confirms the hepatic origin of the ALP.",
    "HashimotosDiseaseRule": "Hashimoto's Thyroiditis is an autoimmune disorder where T-cells chronically infiltrate the thyroid gland, and B-cells produce Anti-TPO antibodies against thyroid peroxidase. This progressive autoimmune destruction gradually destroys the gland's ability to produce thyroid hormones.",
    "HiddenCardiovascularRiskRule": "Apolipoprotein B (ApoB) measures the exact particle count of all atherogenic lipoproteins (LDL, VLDL). Because plaque formation is driven by the number of particles crashing into the arterial wall rather than their total cholesterol weight, ApoB is the ultimate arbiter of cardiovascular risk.",
    "HeartFailureExacerbationRule": "When the heart is struggling to pump against high volume or pressure (volume overload), the ventricular walls are stretched. This physical stretch triggers myocytes to release NT-proBNP, a peptide that attempts to induce diuresis and vasodilation to relieve cardiac wall stress.",
    "OvertrainingSyndromeRule": "Extreme physiological stress triggers the HPA axis to release massive amounts of Cortisol (catabolic), while suppressing the gonadal axis (Testosterone, anabolic). This extreme catabolic shift, paired with autonomic nervous system exhaustion (crashing HRV), defines clinical overtraining syndrome.",
    "EarlyDiabeticNephropathyRule": "Years before eGFR declines, high blood sugar damages the delicate glomerular filtration barrier in the kidneys, allowing microscopic amounts of albumin (Urine ACR) to leak into the urine. Cystatin C, a protein produced by all nucleated cells, is a much earlier and more sensitive marker of this microvascular damage than creatinine.",
    "PrimaryHyperparathyroidismRule": "The parathyroid glands tightly control serum calcium. If calcium is high, PTH should be suppressed. An elevated or inappropriately normal PTH in the face of hypercalcemia indicates an autonomous parathyroid adenoma that is actively leaching calcium from the skeleton, destroying bone density.",
    "AdvancedAnemiaSubtypingRule": "Ferritin represents the body's intracellular iron storage, while Transferrin Saturation (TSAT) measures the iron actively circulating in the blood. When both are completely depleted alongside microcytic cells, the anemia is definitively driven by absolute iron deficiency rather than chronic inflammation."
}

with open(r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\insights\rules\tier3_labs.py', 'r', encoding='utf-8') as f:
    content = f.read()

for rule_name, science_text in science_dict.items():
    pattern = r'(class ' + rule_name + r'\(InsightRule\):\s*\"\"\"[\s\S]*?)(?=CITATIONS:|THRESHOLDS:|RCV INTEGRATION:|CROSS-CORRELATION:|\"\"\")'
    
    def replacer(match):
        return match.group(1) + f"THE SCIENCE:\n    - {science_text}\n\n    "
        
    content = re.sub(pattern, replacer, content, count=1)

with open(r'c:\Users\abhin\Downloads\Zivaa Apps\zivaa-backend\app\services\insights\rules\tier3_labs.py', 'w', encoding='utf-8') as f:
    f.write(content)
