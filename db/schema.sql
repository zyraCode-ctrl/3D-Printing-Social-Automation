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

-- Rolling content queue: products whose AI content is prepared ahead of the daily slot.
-- status: prepared -> publishing -> done (back to prepared when a publish attempt fails).
CREATE TABLE IF NOT EXISTS content_queue (
  product_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('prepared', 'publishing', 'done')),
  prepared_at TEXT NOT NULL,
  claimed_at TEXT,
  completed_at TEXT,
  run_date TEXT,
  run_slot TEXT,
  claim_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  reused_preview INTEGER NOT NULL DEFAULT 0
);

-- Small key/value store for scheduler and sync state (survives container rebuilds via data/db).
CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_overall ON products(overall_status);
CREATE INDEX IF NOT EXISTS idx_queue_status ON content_queue(status, product_id);
CREATE INDEX IF NOT EXISTS idx_logs_product ON logs(product_id, ts);
CREATE INDEX IF NOT EXISTS idx_previews_product ON content_previews(product_id, created_at);
