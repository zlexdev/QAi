"""Importing this subpackage registers every built-in check as a side effect — same
pattern as ``qai.engine.fuzzer.strategies``."""

from __future__ import annotations

from qai.engine.plugins.checks import auth_bypass as auth_bypass
from qai.engine.plugins.checks import idor as idor
from qai.engine.plugins.checks import security_headers as security_headers

__all__ = ["auth_bypass", "idor", "security_headers"]
