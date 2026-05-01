import sys
from sqlalchemy import create_engine, text

from .config import get_database_url

MONOLITH_DEFAULTS = {
    'cpu_units': 512,
    'memory_mb': 1024,
    'min_capacity': 2,
    'max_capacity': 100,
    'rules': {
        'request_count': {
            'target_value': 2500,
            'scale_in_cooldown_sec': 300,
            'scale_out_cooldown_sec': 60,
        },
    }
}

MICROSERVICES_DEFAULTS = {
    'services': {
        'frontend-service': {'cpu_units': 256, 'memory_mb': 512, 'min_capacity': 2, 'max_capacity': 100},
        'product-service': {'cpu_units': 256, 'memory_mb': 512, 'min_capacity': 1, 'max_capacity': 100},
        'cart-service': {'cpu_units': 256, 'memory_mb': 512, 'min_capacity': 1, 'max_capacity': 100},
        'order-service': {'cpu_units': 256, 'memory_mb': 512, 'min_capacity': 1, 'max_capacity': 100},
        'content-service': {'cpu_units': 256, 'memory_mb': 512, 'min_capacity': 1, 'max_capacity': 100},
    },
    'rules': {
        'all': {
            'cpu': {
                'target_value': 70,
                'scale_in_cooldown_sec': 180,
                'scale_out_cooldown_sec': 45,
            },
        },
        'frontend-service': {
            'request_count': {
                'target_value': 5000,
                'scale_in_cooldown_sec': 180,
                'scale_out_cooldown_sec': 45,
            },
        },
    }
}


def migrate(dry_run=False):
    engine = create_engine(get_database_url())

    with engine.begin() as conn:
        # Check if migration already applied (service_name column exists)
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'scaling_rules' AND column_name = 'service_name'
        """))
        if result.fetchone():
            print("Migration already applied (service_name column exists)")
            return

        print("Starting migration: per-service scaling rules")

        # Step 1: Add new columns
        print("\n1. Adding new columns to scaling_rules...")
        conn.execute(text("""
            ALTER TABLE scaling_rules
                ADD COLUMN service_name VARCHAR(50),
                ADD COLUMN min_capacity INTEGER,
                ADD COLUMN max_capacity INTEGER,
                ADD COLUMN cpu_units INTEGER,
                ADD COLUMN memory_mb INTEGER
        """))

        # Step 2: Populate service_name for existing monolith rows
        print("2. Setting service_name on existing rows...")
        conn.execute(text("""
            UPDATE scaling_rules sr
            SET service_name = 'monolith',
                min_capacity = e.min_capacity,
                max_capacity = e.max_capacity,
                cpu_units = e.cpu_units,
                memory_mb = e.ram_in_mb
            FROM experiments e
            WHERE sr.experiment_id = e.id
              AND sr.service_name IS NULL
              AND e.architecture = 'monolith'
        """))

        # Delete old per-experiment microservices rows (will be replaced with per-service in step 4)
        conn.execute(text("""
            DELETE FROM scaling_rules sr
            USING experiments e
            WHERE sr.experiment_id = e.id
              AND sr.service_name IS NULL
              AND e.architecture = 'microservices'
        """))

        # Make service_name NOT NULL
        conn.execute(text("""
            ALTER TABLE scaling_rules ALTER COLUMN service_name SET NOT NULL
        """))

        # Step 3: Drop old unique constraint, add new one
        print("3. Updating unique constraint...")
        result = conn.execute(text("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name = 'scaling_rules' AND constraint_type = 'UNIQUE'
        """))
        for row in result:
            constraint_name = row[0]
            print(f"   Dropping old constraint: {constraint_name}")
            conn.execute(text(f'ALTER TABLE scaling_rules DROP CONSTRAINT "{constraint_name}"'))

        conn.execute(text("""
            ALTER TABLE scaling_rules
                ADD CONSTRAINT uq_scaling_exp_svc_rule UNIQUE (experiment_id, service_name, rule_type)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_scaling_exp_svc ON scaling_rules (experiment_id, service_name)
        """))

        # Step 4: Backfill scaling rules for ECS experiments that don't have any
        print("4. Backfilling scaling rules for ECS experiments...")
        result = conn.execute(text("""
            SELECT e.id, e.architecture, e.cpu_units, e.ram_in_mb, e.min_capacity, e.max_capacity
            FROM experiments e
            LEFT JOIN scaling_rules sr ON sr.experiment_id = e.id
            WHERE e.architecture IN ('monolith', 'microservices')
              AND sr.id IS NULL
        """))
        experiments_to_backfill = result.fetchall()

        for exp in experiments_to_backfill:
            exp_id, arch, exp_cpu, exp_mem, exp_min, exp_max = exp
            print(f"   Backfilling experiment {exp_id} ({arch})...")

            if arch == 'monolith':
                defaults = MONOLITH_DEFAULTS
                cpu = exp_cpu or defaults['cpu_units']
                mem = exp_mem or defaults['memory_mb']
                min_cap = exp_min or defaults['min_capacity']
                max_cap = exp_max or defaults['max_capacity']

                for rule_type, rule in defaults['rules'].items():
                    conn.execute(text("""
                        INSERT INTO scaling_rules
                            (experiment_id, service_name, rule_type, target_value,
                             min_capacity, max_capacity, cpu_units, memory_mb,
                             scale_in_cooldown_sec, scale_out_cooldown_sec)
                        VALUES (:exp_id, 'monolith', :rule_type, :target_value,
                                :min_cap, :max_cap, :cpu, :mem,
                                :scale_in, :scale_out)
                        ON CONFLICT (experiment_id, service_name, rule_type) DO NOTHING
                    """), {
                        'exp_id': exp_id, 'rule_type': rule_type,
                        'target_value': rule['target_value'],
                        'min_cap': min_cap, 'max_cap': max_cap,
                        'cpu': cpu, 'mem': mem,
                        'scale_in': rule['scale_in_cooldown_sec'],
                        'scale_out': rule['scale_out_cooldown_sec'],
                    })

            elif arch == 'microservices':
                ms = MICROSERVICES_DEFAULTS
                for svc_name, svc in ms['services'].items():
                    cpu = exp_cpu or svc['cpu_units']
                    mem = exp_mem or svc['memory_mb']
                    min_cap = svc['min_capacity']
                    max_cap = svc['max_capacity']

                    # CPU rule for all services
                    cpu_rule = ms['rules']['all']['cpu']
                    conn.execute(text("""
                        INSERT INTO scaling_rules
                            (experiment_id, service_name, rule_type, target_value,
                             min_capacity, max_capacity, cpu_units, memory_mb,
                             scale_in_cooldown_sec, scale_out_cooldown_sec)
                        VALUES (:exp_id, :svc, 'cpu', :target_value,
                                :min_cap, :max_cap, :cpu, :mem,
                                :scale_in, :scale_out)
                        ON CONFLICT (experiment_id, service_name, rule_type) DO NOTHING
                    """), {
                        'exp_id': exp_id, 'svc': svc_name,
                        'target_value': cpu_rule['target_value'],
                        'min_cap': min_cap, 'max_cap': max_cap,
                        'cpu': cpu, 'mem': mem,
                        'scale_in': cpu_rule['scale_in_cooldown_sec'],
                        'scale_out': cpu_rule['scale_out_cooldown_sec'],
                    })

                    # Request count rule for frontend only
                    if svc_name in ms['rules']:
                        for rule_type, rule in ms['rules'][svc_name].items():
                            conn.execute(text("""
                                INSERT INTO scaling_rules
                                    (experiment_id, service_name, rule_type, target_value,
                                     min_capacity, max_capacity, cpu_units, memory_mb,
                                     scale_in_cooldown_sec, scale_out_cooldown_sec)
                                VALUES (:exp_id, :svc, :rule_type, :target_value,
                                        :min_cap, :max_cap, :cpu, :mem,
                                        :scale_in, :scale_out)
                                ON CONFLICT (experiment_id, service_name, rule_type) DO NOTHING
                            """), {
                                'exp_id': exp_id, 'svc': svc_name,
                                'rule_type': rule_type,
                                'target_value': rule['target_value'],
                                'min_cap': min_cap, 'max_cap': max_cap,
                                'cpu': cpu, 'mem': mem,
                                'scale_in': rule['scale_in_cooldown_sec'],
                                'scale_out': rule['scale_out_cooldown_sec'],
                            })

        # Step 5: Drop min_capacity/max_capacity from experiments table
        print("5. Dropping min_capacity/max_capacity from experiments table...")
        conn.execute(text("""
            ALTER TABLE experiments
                DROP COLUMN IF EXISTS min_capacity,
                DROP COLUMN IF EXISTS max_capacity
        """))

        if dry_run:
            print("\n[DRY RUN] Rolling back all changes")
            conn.rollback()
        else:
            print("\nMigration complete!")

        # Summary
        result = conn.execute(text("SELECT COUNT(*) FROM scaling_rules"))
        count = result.scalar()
        print(f"Total scaling rules: {count}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("=== DRY RUN MODE ===\n")
    migrate(dry_run=dry_run)