"""Case conversion utilities — single source of truth.

CDP wire format uses camelCase (`allowUnsafeEvalBlockedByCSP`); the vendored
cdp-python module exposes snake_case kwargs (`allow_unsafe_eval_blocked_by_csp`).
Anywhere we bridge the two we use one tested function so acronym handling stays
consistent.

The naive `re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()` shipped before this
module mishandled trailing/embedded acronyms — `...ByCSP` became
`..._by_c_s_p` and `getHTML` became `get_h_t_m_l`. Those names don't exist in
cdp-python, so every CDP command carrying an acronym parameter raised TypeError
on the retry path of `_transport.send_raw`.
"""

import re


# Two-pass regex handling acronym boundaries:
#   1. lower/digit → Upper          ("userAgent"            → "user_Agent")
#   2. acronym end → next word      ("CSPNext", "XMLHttp"   → "CSP_Next", "XML_Http")
# Then lowercase. Order matters: pass 1 splits the easy cases first so pass 2
# only has to handle runs of uppercase that precede a capitalized word.
_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_WORD = re.compile(r"([A-Z]+)([A-Z][a-z])")


def camel_to_snake(name: str) -> str:
    """Convert a camelCase / PascalCase identifier to snake_case.

    Handles trailing acronyms (`...ByCSP` → `..._by_csp`), embedded acronyms
    (`XMLHttpRequest` → `xml_http_request`), all-caps (`URL` → `url`), digits
    (`ipv4Address` → `ipv4_address`), and identifiers already in snake_case.

    Empty string returns empty string.
    """
    s = _LOWER_UPPER.sub(r"\1_\2", name)
    s = _ACRONYM_WORD.sub(r"\1_\2", s)
    return s.lower()
