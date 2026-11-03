"""Widget delivery (step 4.3): the bundle at `/widget/v1/widget.js` (cacheable, versioned by
content hash; a CDN fronts this later), dev-only embed test pages at `/widget/test/<page>.html`,
and CORS for the public widget API (any origin may preflight; the per-institution origin
allowlist is enforced by the endpoints themselves, bound into the session token)."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import REPO_ROOT, Settings

router = APIRouter(prefix="/widget", tags=["widget-assets"])
TEST_PAGES = REPO_ROOT / "widget" / "test-pages"
PAGE_RE = re.compile(r"^[a-z0-9-]+\.html$")
CORS_PREFIX = "/api/v1/widget/"
CORS_HEADERS = [
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-allow-headers", b"authorization, content-type"),
    (b"access-control-max-age", b"600"),
]


@lru_cache(maxsize=8)
def _version(path: Path, mtime: float) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


@router.get("/v1/widget.js")
async def widget_js(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    path = settings.widget_dist_dir / "v1" / "widget.js"
    if not path.is_file():
        raise HTTPException(404, "widget bundle not built (pnpm -C widget build)")
    version = _version(path, path.stat().st_mtime)
    if request.headers.get("if-none-match") == f'"{version}"':
        return Response(status_code=304)
    return FileResponse(
        path,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "ETag": f'"{version}"',
            "X-Widget-Version": version,
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/test/{page}")
async def test_page(page: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    if settings.env == "prod" or not PAGE_RE.match(page) or not (TEST_PAGES / page).is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(TEST_PAGES / page, media_type="text/html; charset=utf-8")


class WidgetCorsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(CORS_PREFIX):
            await self.app(scope, receive, send)
            return
        origin = dict(scope["headers"]).get(b"origin")
        if origin is None:
            await self.app(scope, receive, send)
            return
        allow = [(b"access-control-allow-origin", origin), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS":
            await send(
                {"type": "http.response.start", "status": 204, "headers": allow + CORS_HEADERS}
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + allow
            await send(message)

        await self.app(scope, receive, send_with_cors)
