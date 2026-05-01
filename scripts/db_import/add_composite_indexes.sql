BEGIN;

CREATE INDEX IF NOT EXISTS idx_req_exp_xpair ON requests (experiment_id, x_pair);

CREATE INDEX IF NOT EXISTS idx_handler_exp_xpair ON handler_events (experiment_id, x_pair);
CREATE INDEX IF NOT EXISTS idx_handler_exp_phase_idx ON handler_events (experiment_id, phase_index);

CREATE INDEX IF NOT EXISTS idx_rpc_exp_xpair ON rpc_calls (experiment_id, x_pair);

CREATE INDEX IF NOT EXISTS idx_req_exp_context ON requests (experiment_id, context_id);
CREATE INDEX IF NOT EXISTS idx_handler_exp_context ON handler_events (experiment_id, context_id);
CREATE INDEX IF NOT EXISTS idx_rpc_exp_context ON rpc_calls (experiment_id, context_id);

CREATE INDEX IF NOT EXISTS idx_req_exp_xpair_notnull ON requests (experiment_id, x_pair) WHERE x_pair IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_handler_exp_xpair_notnull ON handler_events (experiment_id, x_pair) WHERE x_pair IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rpc_exp_xpair_notnull ON rpc_calls (experiment_id, x_pair) WHERE x_pair IS NOT NULL;

COMMIT;

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