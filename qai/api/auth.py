from __future__ import annotations

import secrets

from fastapi import Depends
from fastapi.security import APIKeyHeader

from qai.api.errors import InvalidApiKeyError
from qai.api.settings import Settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_settings() -> Settings:
    # pydantic-settings fills api_key from the QAI_API_KEY env var, not this call site.
    return Settings()


async def require_api_key(
    presented: str | None = Depends(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    if presented is None or not secrets.compare_digest(presented, settings.api_key):
        raise InvalidApiKeyError
