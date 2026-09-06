-- Alter fhir_diagnostic_reports table to allow NULL effective_datetime 
-- This is necessary to support background asynchronous extraction where 
-- the LLM may fail to find a date, allowing us to store it as a "draft".

ALTER TABLE fhir_diagnostic_reports
ALTER COLUMN effective_datetime DROP NOT NULL;
