PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
  product_id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  extra_files TEXT NOT NULL DEFAULT '[]',
  media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video', 'both')),
  instagram_status TEXT NOT NULL DEFAULT 'pending',
  facebook_status TEXT NOT NULL DEFAULT 'pending',
  pinterest_status TEXT NOT NULL DEFAULT 'pending',
  youtube_status TEXT NOT NULL DEFAULT 'pending',
  instagram_post_id TEXT,
  facebook_post_id TEXT,
  pinterest_post_id TEXT,
  youtube_post_id TEXT,
  overall_status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  dry_run INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  published_at TEXT
);

CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  event TEXT NOT NULL,
  product_id INTEGER,
  platform TEXT,
  message TEXT NOT NULL,
  details TEXT
);

CREATE TABLE IF NOT EXISTS content_previews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  content_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_overall ON products(overall_status);
CREATE INDEX IF NOT EXISTS idx_logs_product ON logs(product_id, ts);
CREATE INDEX IF NOT EXISTS idx_previews_product ON content_previews(product_id, created_at);
