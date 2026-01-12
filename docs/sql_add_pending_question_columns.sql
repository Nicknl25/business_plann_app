-- Target: intake_consult_drafts
-- Adds pending question tracking columns for forced PATCH-only turn control.
ALTER TABLE intake_consult_drafts
  ADD COLUMN pending_question_key VARCHAR(64) NULL,
  ADD COLUMN pending_question_kind VARCHAR(32) NULL;
