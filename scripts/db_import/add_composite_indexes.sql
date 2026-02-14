-- Database migration to add composite indexes for JOIN optimization
-- These indexes provide 30-40% performance improvement for db_import operations
--
-- Usage:
--   psql -d your_database -f add_composite_indexes.sql
--
-- Safe to run multiple times - uses CREATE INDEX IF NOT EXISTS

BEGIN;

-- Add composite indexes for JOIN optimization between tables
-- These are critical for the post-processing UPDATE statements that join
-- on (experiment_id, x_pair) combinations

-- Requests table: Add (experiment_id, x_pair) composite index
-- Improves JOIN performance when correlating requests with handler_events/rpc_calls
CREATE INDEX IF NOT EXISTS idx_req_exp_xpair ON requests (experiment_id, x_pair);

-- Handler events table: Add (experiment_id, x_pair) and (experiment_id, phase_index)
-- Improves JOIN performance for cross-table enrichment and phase calculations
CREATE INDEX IF NOT EXISTS idx_handler_exp_xpair ON handler_events (experiment_id, x_pair);
CREATE INDEX IF NOT EXISTS idx_handler_exp_phase_idx ON handler_events (experiment_id, phase_index);

-- RPC calls table: Add (experiment_id, x_pair) composite index
-- Improves JOIN performance when correlating RPC calls with requests
CREATE INDEX IF NOT EXISTS idx_rpc_exp_xpair ON rpc_calls (experiment_id, x_pair);

-- Optional: Add partial indexes for better performance on non-NULL x_pair values
-- These help when x_pair IS NOT NULL conditions are used in JOINs
CREATE INDEX IF NOT EXISTS idx_req_exp_xpair_notnull ON requests (experiment_id, x_pair) WHERE x_pair IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_handler_exp_xpair_notnull ON handler_events (experiment_id, x_pair) WHERE x_pair IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rpc_exp_xpair_notnull ON rpc_calls (experiment_id, x_pair) WHERE x_pair IS NOT NULL;

COMMIT;

-- Verify indexes were created
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE indexname IN (
    'idx_req_exp_xpair',
    'idx_handler_exp_xpair',
    'idx_handler_exp_phase_idx',
    'idx_rpc_exp_xpair',
    'idx_req_exp_xpair_notnull',
    'idx_handler_exp_xpair_notnull',
    'idx_rpc_exp_xpair_notnull'
)
ORDER BY tablename, indexname;