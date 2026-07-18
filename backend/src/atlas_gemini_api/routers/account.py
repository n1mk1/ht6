from typing import Annotated, Any

from fastapi import APIRouter, Depends

from atlas_gemini_api.dependencies import require_user

router = APIRouter(tags=["account"])
CurrentUser = Annotated[dict[str, Any], Depends(require_user)]


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return {
        "sub": user.get("sub"),
        "permissions": user.get("permissions", []),
        "scope": user.get("scope", ""),
    }
