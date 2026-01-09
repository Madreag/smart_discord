-- Add pre_prompt column to guilds table
-- Allows setting a global personality/rules that get injected into all bot responses

ALTER TABLE guilds ADD COLUMN IF NOT EXISTS pre_prompt TEXT;

COMMENT ON COLUMN guilds.pre_prompt IS 'Custom system prompt injected into all bot responses for this guild';
