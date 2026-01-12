-- Target: intake_consult_drafts
-- Adds flow-state columns to enforce ordered intake.
ALTER TABLE intake_consult_drafts
  ADD COLUMN current_model_key VARCHAR(64) NULL,
  ADD COLUMN current_field_key VARCHAR(64) NULL;
