"""Internal endpoints. `GET /internal/tools` — MCP-style manifest of the agent's tools
(PLAN §5 DO) so they could be served over MCP later. Staff+ (schemas only, no tenant data)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.agent.tools import build_registry
from app.api.deps import require_role
from app.core.tenancy import TenantContext

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/tools")
async def tools_manifest(
    ctx: Annotated[TenantContext, Depends(require_role("staff"))],
) -> dict[str, Any]:
    return build_registry().manifest()
