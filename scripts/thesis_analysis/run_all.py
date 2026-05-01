#!/usr/bin/env python3
"""
Master script: run all thesis analysis scripts in sequence.
Usage: python run_all.py [--only 02,05,12] [--skip 06]
"""

import sys
import os
import time
import importlib
import argparse

SCRIPTS = [
    ('01', '01_experiment_overview'),
    ('02', '02_baseline_latency'),
    ('03', '03_phase_analysis'),
    ('04', '04_algorithm_comparison'),
    ('05', '05_hardware_scaling'),
    ('06', '06_cold_start_analysis'),
    ('07', '07_error_analysis'),
    ('08', '08_edge_auth_analysis'),
    ('09', '09_protected_endpoint_analysis'),
    ('10', '10_throughput_analysis'),
    ('11', '11_decision_framework'),
    ('12', '12_insights_finder'),
    ('13', '13_deep_analysis'),
    ('14', '14_extended_analysis'),
    ('15', '15_comprehensive_delta_auth'),
    ('16', '16_phase_overhead_evolution'),
    ('17', '17_algorithm_impact'),
    ('18', '18_latency_predictability'),
    ('19', '19_cost_performance'),
    ('20', '20_multiplication_model_validation'),
    ('21', '21_complete_decision_framework'),
    ('22', '22_cdf_and_cold_start_auth'),
    ('23', '23_auth_only_delta_auth'),
    ('24', '24_cognito_verification_time'),
    ('25', '25_cognito_percentile_progression'),
    ('26', '26_overhead_excl_login'),
    ('27', '27_baseline_vs_flashcrowd'),
    ('28', '28_boxplots_auth_only'),
    ('29', '29_hw_scaling_delta_auth'),
    ('30', '30_edge_vs_cognito_monolith'),
    ('31', '31_edge_selective_analysis'),
    ('32', '32_edge_cognito_crossover'),
    ('33', '33_auth_only_p99_all_hw'),
    ('34', '34_bootstrap_ci_delta_auth'),
    ('35', '35_nonparametric_tests'),
    ('36', '36_timeseries_latency'),
    ('37', '37_distribution_visualization'),
    ('38', '38_factorial_analysis'),
    ('39', '39_scientific_benchmarking'),
    ('40', '40_discover_new_experiments'),
    ('41', '41_anova_contrasts'),
    ('42', '42_anova_phase_analysis'),
    ('43', '43_architecture_ratio_compression'),
    ('44', '44_cpu_saturation'),
    ('45', '45_chapter_numbers'),
    ('46', '46_replot_broken_axis'),
    ('47', '47_multiplication_ratio_ci'),
]


def main():
    parser = argparse.ArgumentParser(description='Run thesis analysis scripts')
    parser.add_argument('--only', type=str, help='Comma-separated list of script numbers to run (e.g., 02,05)')
    parser.add_argument('--skip', type=str, help='Comma-separated list of script numbers to skip')
    args = parser.parse_args()

    only = set(args.only.split(',')) if args.only else None
    skip = set(args.skip.split(',')) if args.skip else set()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    results = []

    for num, module_name in SCRIPTS:
        if only and num not in only:
            continue
        if num in skip:
            print(f"\n{'='*70}\nSKIPPING {module_name}\n{'='*70}")
            continue

        start = time.time()
        try:
            mod = importlib.import_module(module_name)
            mod.main()
            elapsed = time.time() - start
            results.append((num, module_name, 'OK', elapsed))
            print(f"\n--- Completed {module_name} in {elapsed:.1f}s ---")
        except Exception as e:
            elapsed = time.time() - start
            results.append((num, module_name, f'FAILED: {e}', elapsed))
            print(f"\n--- FAILED {module_name}: {e} ({elapsed:.1f}s) ---")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*70}")
    print(f"ALL ANALYSES COMPLETE")
    print(f"{'='*70}")
    for num, name, status, elapsed in results:
        icon = 'OK' if status == 'OK' else 'FAIL'
        print(f"  [{icon:4s}] {num} {name:40s} {elapsed:6.1f}s")


if __name__ == '__main__':
    main()
