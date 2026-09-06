import asyncio
import os
from dotenv import load_dotenv

load_dotenv("C:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env")

from app.services.medgemma_services import parse_lab_report_to_fhir
import json

async def test_llm():
    # Use a dummy text to simulate the PDF just to see the structure
    # Actually, we don't have the PDF, but we can send a simple text file
    file_bytes = b"Laboratory Report\nPatient: Dummy\nTest: Microalbumin\nResult: 32.0 mg/L\nTest: Urine Bacteria\nResult: Present"
    mime_type = "text/plain"
    
    print("Calling MedGemma...")
    bundle = await parse_lab_report_to_fhir(file_bytes, mime_type)
    print(json.dumps(bundle, indent=2))

if __name__ == "__main__":
    asyncio.run(test_llm())
