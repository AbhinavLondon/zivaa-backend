import asyncio
from app.services.loinc_dictionary import get_loinc_mapping
from app.services.loinc_vector_search import search_tier2_loinc_database

async def main():
    test_cases = [
        ("Basophils", "thou/mm3"),
        ("Basophils", "%")
    ]
    
    for test_name, unit in test_cases:
        # Mock what medgemma_services.py does
        specimen_type = None # or 'Blood'
        search_term = f"{test_name} in {specimen_type}" if specimen_type else test_name
        
        if unit:
            unit_lower = unit.lower()
            if "%" in unit_lower or "percentage" in unit_lower or "nfr" in unit_lower or "vfr" in unit_lower:
                search_term += " percentage"
            elif any(x in unit_lower for x in ["thou/mm3", "abs", "10*3", "#"]):
                search_term += " absolute"
                
        mapping = get_loinc_mapping(search_term)
        if not mapping:
            mapping = await search_tier2_loinc_database(search_term)
            
        print(f"Test Name: '{test_name}', Unit: '{unit}' -> Search Term: '{search_term}' -> Mapping: {mapping}")

if __name__ == "__main__":
    asyncio.run(main())
