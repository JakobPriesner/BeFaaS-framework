"""Importing this package triggers every @register decorator.

Add a new group: create `<group>.py` in this directory, register `Number`
factories with `@register`, then import the module here.
"""

from thesis_numbers.definitions import dataset  # noqa: F401
from thesis_numbers.definitions import dataset_per_arch  # noqa: F401
from thesis_numbers.definitions import dataset_phases  # noqa: F401
from thesis_numbers.definitions import rq1_aggregate  # noqa: F401
from thesis_numbers.definitions import rq1_arch_ratios  # noqa: F401
# rq1_handler_leaf disabled: payment/cartkvstorage are internal Lambda
# handlers, not external API endpoints, so the requests table has no rows
# with these endpoints. The 17--18 ms handler beitrag is measured from
# CloudWatch handler logs which aren't in this DB.
# from thesis_numbers.definitions import rq1_handler_leaf  # noqa: F401
from thesis_numbers.definitions import rq1_auth_only  # noqa: F401
from thesis_numbers.definitions import rq1_login_exclusion  # noqa: F401
from thesis_numbers.definitions import rq2_multiplication  # noqa: F401
from thesis_numbers.definitions import rq2_per_endpoint  # noqa: F401
from thesis_numbers.definitions import rq2_cascading  # noqa: F401
from thesis_numbers.definitions import rq3_exposure  # noqa: F401
from thesis_numbers.definitions import rq4_algorithm_impact  # noqa: F401
from thesis_numbers.definitions import rq4_decision_matrix  # noqa: F401
from thesis_numbers.definitions import rq4_equalizing  # noqa: F401
# rq1_welch disabled: block-P99 definition here does not match the
# methodology used in tab:significance-tests-full (which is curated from
# script 41_anova_contrasts.py). Add back once the block aggregation is
# reconciled with the appendix table.
# from thesis_numbers.definitions import rq1_welch  # noqa: F401
