CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    location TEXT,
    starts_at TEXT,
    registration_deadline_at TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'open', 'closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS option_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL
        REFERENCES events (id) ON DELETE CASCADE,
    kind TEXT NOT NULL
        CHECK (kind IN ('attendance', 'custom')),
    title TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1
        CHECK (required IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL
        REFERENCES option_groups (id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL
        REFERENCES events (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    attendance TEXT NOT NULL
        CHECK (attendance IN ('attending', 'not_attending')),
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (event_id, name_normalized)
);

CREATE TABLE IF NOT EXISTS registration_choices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL
        REFERENCES registrations (id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL
        REFERENCES option_groups (id),
    option_id INTEGER NOT NULL
        REFERENCES options (id),
    option_label TEXT NOT NULL,
    group_title TEXT NOT NULL,
    UNIQUE (registration_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_option_groups_event
    ON option_groups (event_id);

CREATE INDEX IF NOT EXISTS idx_options_group
    ON options (group_id);

CREATE INDEX IF NOT EXISTS idx_registrations_event
    ON registrations (event_id);

CREATE INDEX IF NOT EXISTS idx_choices_registration
    ON registration_choices (registration_id);
