CREATE TABLE system(key, value);
INSERT INTO system (key, value) VALUES ('VERSION', 1);
CREATE TABLE messages(timestamp, role, content, tool_calls);