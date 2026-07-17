CREATE TABLE system(key, value);
INSERT INTO system (key, value) VALUES ('VERSION', 1);
CREATE TABLE parcels(
    tracking_number TEXT UNIQUE,
    carrier TEXT,
    description TEXT,
    created INTEGER,
    last_status TEXT,
    last_status_time INTEGER,
    last_polled INTEGER,
    active INTEGER
);
