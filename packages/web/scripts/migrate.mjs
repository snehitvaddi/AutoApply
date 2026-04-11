#!/usr/bin/env node
/**
 * Supabase Migration Runner — runs SQL migrations against the live Postgres DB.
 *
 * Invoked from package.json "build" script BEFORE `next build`, so every Vercel
 * deploy automatically picks up new migrations.
 *
 * Design:
 *   - Reads SQL files from ../../../supabase/migrations/ (repo-root supabase dir)
 *   - Connects via SUPABASE_DB_URL env var (direct Postgres pooler URL)
 *   - Tracks applied migrations in a `_migrations` table (auto-created on first run)
 *   - Each migration runs inside a transaction; failure rolls back cleanly
 *   - Fails the Vercel build if any migration fails (safer than silent drift)
 *   - SAFE SKIP if SUPABASE_DB_URL is not set — so local `npm run dev` still works
 *     without needing the DB connection string.
 *
 * Required env var in Vercel:
 *   SUPABASE_DB_URL — from Supabase dashboard → Settings → Database → Connection string
 *   Use the "Transaction" pooler URL format:
 *     postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
 */
import pg from "pg";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DB_URL = process.env.SUPABASE_DB_URL;

if (!DB_URL) {
  console.warn("[migrate] SUPABASE_DB_URL not set — skipping migrations (local dev is fine)");
  process.exit(0);
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// packages/web/scripts → repo root is 3 levels up
const MIGRATIONS_DIR = path.resolve(__dirname, "..", "..", "..", "supabase", "migrations");

if (!fs.existsSync(MIGRATIONS_DIR)) {
  console.warn(`[migrate] migrations dir not found: ${MIGRATIONS_DIR}`);
  process.exit(0);
}

console.log(`[migrate] using migrations from: ${MIGRATIONS_DIR}`);

const client = new pg.Client({
  connectionString: DB_URL,
  // Supabase pooler requires SSL; accept their self-signed cert.
  ssl: { rejectUnauthorized: false },
  // Short connect timeout so a bad URL fails the build fast.
  connectionTimeoutMillis: 15000,
  query_timeout: 120000,
});

try {
  await client.connect();
  console.log("[migrate] connected");

  // Bootstrap the tracking table.
  await client.query(`
    CREATE TABLE IF NOT EXISTS public._migrations (
      name text PRIMARY KEY,
      applied_at timestamptz NOT NULL DEFAULT now(),
      checksum text
    )
  `);

  const files = fs
    .readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  const { rows: appliedRows } = await client.query(
    "SELECT name FROM public._migrations"
  );
  const applied = new Set(appliedRows.map((r) => r.name));

  let ranCount = 0;
  for (const file of files) {
    if (applied.has(file)) {
      continue;
    }
    console.log(`[migrate] applying ${file} ...`);
    const sqlPath = path.join(MIGRATIONS_DIR, file);
    const sql = fs.readFileSync(sqlPath, "utf8");

    await client.query("BEGIN");
    try {
      await client.query(sql);
      await client.query(
        "INSERT INTO public._migrations (name) VALUES ($1)",
        [file]
      );
      await client.query("COMMIT");
      ranCount += 1;
      console.log(`[migrate] ✓ ${file}`);
    } catch (err) {
      await client.query("ROLLBACK");
      console.error(`[migrate] ✗ ${file}:`, err.message);
      throw err;
    }
  }

  if (ranCount === 0) {
    console.log("[migrate] nothing to do — all migrations already applied");
  } else {
    console.log(`[migrate] done — ${ranCount} new migration(s) applied`);
  }
} catch (err) {
  console.error("[migrate] FATAL:", err.message);
  process.exit(1);
} finally {
  try {
    await client.end();
  } catch {
    /* ignore */
  }
}
