"""LaTeX-safe formatters for German scientific prose.

All outputs use the German decimal comma via `{,}` so LaTeX treats it as a
regular character with no surrounding space. Units attach with `\\,` (thin
non-breaking space), matching the siunitx convention used elsewhere in the
thesis.
"""

from __future__ import annotations


def _de(value: float, decimals: int) -> str:
    s = f"{value:.{decimals}f}"
    return s.replace(".", "{,}")


def de_int(value: float) -> str:
    """Unsigned integer with thin-space thousands separator."""
    n = int(round(value))
    out = f"{n:,}".replace(",", "\\,")
    return out


def de_ms(value: float, decimals: int = 0) -> str:
    """Unsigned latency in milliseconds: '446\\,ms' or '14{,}3\\,ms'."""
    return f"{_de(value, decimals)}\\,ms"


def de_ms_signed(value: float, decimals: int = 0) -> str:
    """Signed delta in ms: '+14{,}3\\,ms' or '-80\\,ms'."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}{_de(abs(value), decimals)}\\,ms"


def de_pct(value: float, decimals: int = 1) -> str:
    """Percentage: '18{,}4\\,\\%'. Input is the percent value, not fraction."""
    return f"{_de(value, decimals)}\\,\\%"


def de_pct_signed(value: float, decimals: int = 1) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{_de(abs(value), decimals)}\\,\\%"


def de_ratio(value: float, decimals: int = 2) -> str:
    """Unitless ratio: '3{,}19'."""
    return _de(value, decimals)


def de_ratio_times(value: float, decimals: int = 1) -> str:
    """Multiplicative factor with times symbol: '3{,}2$\\times$'."""
    return f"{_de(value, decimals)}$\\times$"


def de_ci(low: float, high: float, decimals: int = 2, unit: str = "") -> str:
    """95% confidence interval: '[2{,}95,\\; 3{,}43]' or with unit."""
    u = f"\\,{unit}" if unit else ""
    return f"[{_de(low, decimals)}{u},\\;{_de(high, decimals)}{u}]"


def de_mb(value: float) -> str:
    """Memory in MiB: '512\\,MB'."""
    return f"{int(round(value))}\\,MB"


def de_millions(value: float, decimals: int = 1) -> str:
    """Counts in millions: '96{,}3\\,Mio.' for 96_337_000."""
    return f"{_de(value / 1e6, decimals)}\\,Mio."


def de_thousands(value: float, decimals: int = 0) -> str:
    return f"{_de(value / 1e3, decimals)}\\,Tsd."


def de_p_value(p: float) -> str:
    """Statistical p-value: '$< 0{,}001$' or '$= 0{,}034$'."""
    if p < 0.001:
        return "$< 0{,}001$"
    return f"$= {_de(p, 3)}$"
