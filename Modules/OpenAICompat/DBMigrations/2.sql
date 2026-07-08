ALTER TABLE messages ADD COLUMN 'tool_call_id';
UPDATE messages SET tool_call_id = '';
UPDATE system SET value = 3 WHERE KEY = 'VERSION';
