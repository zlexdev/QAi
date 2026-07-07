"""auth — one-time login recording (record_login) and deterministic replay
(replay_login), producing an AuthResult that feeds the engine's existing
``cookies=``/``default_headers`` mechanisms. See `_MODULE.md`."""

from __future__ import annotations
