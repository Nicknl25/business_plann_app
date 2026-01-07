-- Add dedicated operating-expense model columns to the unified intake drafts table.
-- Target: intake_consult_drafts

ALTER TABLE intake_consult_drafts
  ADD COLUMN cogs_model_json JSON NULL,
  ADD COLUMN gna_model_json JSON NULL,
  ADD COLUMN year1_cogs DECIMAL(18,2) NULL,
  ADD COLUMN year1_gna_total DECIMAL(18,2) NULL;

