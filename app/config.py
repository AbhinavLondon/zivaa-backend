import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Zivaa Eldercare Platform"

    # Vertex AI / MedGemma Configuration
    ENABLE_MEDGEMMA_PIPELINE: bool = os.getenv("ENABLE_MEDGEMMA_PIPELINE", "False").lower() == "true"
    FORCE_GEMINI: bool = os.getenv("FORCE_GEMINI", "False").lower() == "true"
    VERTEX_PROJECT_ID: str = os.getenv("VERTEX_PROJECT_ID", "zivaa-gcp-project")
    VERTEX_REGION: str = os.getenv("VERTEX_REGION", "us-central1")
    VERTEX_API_KEY: str = os.getenv("VERTEX_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    USDA_API_KEY: str = os.getenv("USDA_API_KEY", "")
    MEDGEMMA_MODEL_NAME: str = os.getenv("MEDGEMMA_MODEL_NAME", "medlm-large")
    MEDGEMMA_API_URL: str = os.getenv("MEDGEMMA_API_URL", "") # Custom URL (e.g. for vLLM, local, or proxy testing)
    
    # LOINC API Configuration
    LOINC_USERNAME: str = os.getenv("LOINC_USERNAME", "")
    LOINC_PASSWORD: str = os.getenv("LOINC_PASSWORD", "")

settings = Settings()
