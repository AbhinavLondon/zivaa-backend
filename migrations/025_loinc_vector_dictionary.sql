-- Enable pgvector extension (Supabase supports this natively)
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the massive Tier 2 LOINC dictionary table
CREATE TABLE IF NOT EXISTS loinc_universal_dictionary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loinc_code VARCHAR(50) NOT NULL UNIQUE,
    component VARCHAR(255) NOT NULL, -- e.g., 'Glucose'
    property VARCHAR(100), -- e.g., 'MCnc' (Mass Concentration)
    time_aspect VARCHAR(50), -- e.g., 'Pt' (Point in time)
    system VARCHAR(100), -- e.g., 'Ser/Plas' (Serum/Plasma)
    scale_type VARCHAR(50), -- e.g., 'Qn' (Quantitative)
    method_type VARCHAR(100), 
    long_common_name VARCHAR(500) NOT NULL,
    shortname VARCHAR(255),
    status VARCHAR(50), -- e.g., 'ACTIVE'
    
    -- The vector embedding of the long_common_name (using 768 dimensions for Google text-embedding-004)
    name_embedding vector(768),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create a semantic search function for Supabase RPC
CREATE OR REPLACE FUNCTION match_loinc_biomarker(
    query_embedding vector(768), 
    match_threshold float, 
    match_count int
)
RETURNS TABLE (
    loinc_code VARCHAR,
    long_common_name VARCHAR,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        l.loinc_code,
        l.long_common_name,
        1 - (l.name_embedding <=> query_embedding) AS similarity
    FROM loinc_universal_dictionary l
    WHERE 1 - (l.name_embedding <=> query_embedding) > match_threshold
    ORDER BY l.name_embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Create an index for vector search performance (HNSW)
CREATE INDEX ON loinc_universal_dictionary 
USING hnsw (name_embedding vector_cosine_ops);
