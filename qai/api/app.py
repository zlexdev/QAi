from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from scalar_fastapi import get_scalar_api_reference

from qai.api.errors import InvalidApiKeyError, JobNotFoundError
from qai.api.routes import health_router, jobs_router, pipeline_router, scan_router
from qai.api.settings import Settings
from qai.engine.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="QAi remote API", version="0.1.0")

    app.include_router(health_router)
    app.include_router(scan_router)
    app.include_router(jobs_router)
    app.include_router(pipeline_router)

    @app.get("/scalar", include_in_schema=False)
    async def scalar_docs() -> HTMLResponse:
        return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)

    @app.exception_handler(JobNotFoundError)
    async def _job_not_found(_request: Request, exc: JobNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc), "error_type": "JobNotFoundError"})

    @app.exception_handler(InvalidApiKeyError)
    async def _invalid_api_key(_request: Request, _exc: InvalidApiKeyError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid or missing X-API-Key", "error_type": "InvalidApiKeyError"},
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    # Fails loud (pydantic ValidationError) if QAI_API_KEY is unset.
    settings = Settings()
    # Single worker: JobStore/PipelineRuntime are in-process state — a multi-worker
    # run would silently split jobs/sessions across processes (see 00-overview.md Risks).
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    main()
