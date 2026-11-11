-- MAYA andmebaasi skeem.
-- GENEREERITUD: python3 init_db.py --dump
-- Ära muuda käsitsi – skeem tuleb moodulite init-funktsioonidest.

-- ===== reminders.db ==============================================
CREATE TRIGGER archive_fts_ad AFTER DELETE ON conversation_archive BEGIN
            INSERT INTO archive_fts(archive_fts, rowid, user_text, reply_text)
            VALUES ('delete', old.id, old.user_text, old.reply_text);
        END;
CREATE TRIGGER archive_fts_ai AFTER INSERT ON conversation_archive BEGIN
            INSERT INTO archive_fts(rowid, user_text, reply_text)
            VALUES (new.id, new.user_text, new.reply_text);
        END;
CREATE TRIGGER archive_fts_au AFTER UPDATE ON conversation_archive BEGIN
            INSERT INTO archive_fts(archive_fts, rowid, user_text, reply_text)
            VALUES ('delete', old.id, old.user_text, old.reply_text);
            INSERT INTO archive_fts(rowid, user_text, reply_text)
            VALUES (new.id, new.user_text, new.reply_text);
        END;
CREATE TRIGGER memory_fts_ad AFTER DELETE ON memory BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, fact) VALUES ('delete', old.id, old.fact);
        END;
CREATE TRIGGER memory_fts_ai AFTER INSERT ON memory BEGIN
            INSERT INTO memory_fts(rowid, fact) VALUES (new.id, new.fact);
        END;
CREATE TRIGGER memory_fts_au AFTER UPDATE ON memory BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, fact) VALUES ('delete', old.id, old.fact);
            INSERT INTO memory_fts(rowid, fact) VALUES (new.id, new.fact);
        END;
CREATE VIRTUAL TABLE archive_fts USING fts5(
                user_text, reply_text,
                content='conversation_archive',
                content_rowid='id',
                tokenize="unicode61 remove_diacritics 0",
                prefix='3 4 5'
            );
CREATE TABLE 'archive_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'archive_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'archive_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE 'archive_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE conversation_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date_str TEXT NOT NULL,
            weekday_str TEXT NOT NULL,
            user_text TEXT NOT NULL,
            reply_text TEXT NOT NULL
        , persona TEXT);
CREATE TABLE logbook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            category TEXT,
            entry_text TEXT
        );
CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            fact TEXT NOT NULL UNIQUE
        , category TEXT NOT NULL DEFAULT 'muu', confidence REAL NOT NULL DEFAULT 0.6, source TEXT NOT NULL DEFAULT 'tundmatu', status TEXT NOT NULL DEFAULT 'active', norm_key TEXT NOT NULL DEFAULT '', subject_key TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', superseded_by INTEGER, hit_count INTEGER NOT NULL DEFAULT 0, persona TEXT, scope TEXT NOT NULL DEFAULT 'shared', scope_reason TEXT);
CREATE VIRTUAL TABLE memory_fts USING fts5(
                fact,
                content='memory',
                content_rowid='id',
                tokenize="unicode61 remove_diacritics 0",
                prefix='3 4 5'
            );
CREATE TABLE 'memory_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'memory_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'memory_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE 'memory_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_time TEXT NOT NULL,
            reminder_text TEXT NOT NULL,
            is_done INTEGER DEFAULT 0
        );
CREATE TABLE settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        );
CREATE TABLE shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            added_at TEXT NOT NULL
        );
CREATE TABLE sqlite_sequence(name,seq);
CREATE INDEX idx_archive_date ON conversation_archive(date_str);
CREATE INDEX idx_mem_fact ON memory(fact);
CREATE INDEX idx_mem_norm ON memory(norm_key);
CREATE INDEX idx_mem_scope ON memory(scope, persona, status);
CREATE INDEX idx_mem_status ON memory(status);
CREATE INDEX idx_mem_subject ON memory(subject_key, status);

