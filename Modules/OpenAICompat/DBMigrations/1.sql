ALTER TABLE messages ADD COLUMN 'tool_context';
UPDATE messages SET tool_context = '';
UPDATE system SET value = 2 WHERE KEY = 'VERSION';