from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_config
from app.errors import register as register_errors
from app.lifespan import lifespan
from app.routes.admin.auth.router import router as admin_auth_router
from app.routes.admin.codetours.router import router as admin_codetours_router
from app.routes.admin.health.router import router as admin_health_router
from app.routes.admin.llm_sessions.router import router as admin_llm_sessions_router
from app.routes.admin.presets.router import router as admin_presets_router
from app.routes.admin.trace.router import router as admin_trace_router
from app.routes.bundles.router import router as bundles_router
from app.routes.codetours.router import router as codetours_router
from app.routes.docs.router import router as docs_router
from app.routes.generations.router import router as generations_router
from app.routes.health import router as health_router
from app.routes.logs.router import router as logs_router
from app.routes.metrics.router import router as metrics_router
from app.routes.pipelines.router import router as pipelines_router
from app.routes.repos.router import router as repos_router
from app.routes.runtime.router import router as runtime_router
from app.routes.search.router import router as search_router
from app.routes.streams.router import router as streams_router
from app.routes.tasks.resume import router as tasks_resume_router
from app.routes.tasks.retry import router as tasks_retry_router
from app.routes.tasks.router import router as tasks_router
from app.routes.tasks.stop import router as tasks_stop_router
from app.routes.wiki.router import router as wiki_router


def create_app() -> FastAPI:
    config = get_config()

    app = FastAPI(
        title="Source2Doc Gateway API",
        description="Gateway API for source2doc infrastructure",
        version="0.1.0",
        lifespan=lifespan,
        debug=config.debug,
    )

    app.state.config = config

    register_errors(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(streams_router)
    app.include_router(pipelines_router)
    app.include_router(logs_router)
    app.include_router(docs_router)
    app.include_router(wiki_router)
    app.include_router(tasks_router)
    app.include_router(tasks_retry_router)
    app.include_router(tasks_resume_router)
    app.include_router(tasks_stop_router)
    app.include_router(repos_router)
    app.include_router(search_router)
    app.include_router(bundles_router)
    app.include_router(codetours_router)
    app.include_router(generations_router)
    app.include_router(metrics_router)
    app.include_router(runtime_router)
    app.include_router(admin_auth_router)
    app.include_router(admin_presets_router)
    app.include_router(admin_codetours_router)
    app.include_router(admin_health_router)
    app.include_router(admin_llm_sessions_router)
    app.include_router(admin_trace_router)

    return app


app = create_app()
