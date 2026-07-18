from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from atlas_gemini_api.dependencies import get_gemini_client, require_user
from atlas_gemini_api.models import GenerateRequest, GenerateResponse

router = APIRouter(prefix="/ai", tags=["ai"])
CurrentUser = Annotated[dict[str, Any], Depends(require_user)]
GeminiClient = Annotated[Any, Depends(get_gemini_client)]


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    request: Request,
    _user: CurrentUser,
    client: GeminiClient,
) -> GenerateResponse:
    settings = request.app.state.settings
    try:
        interaction = await client.aio.interactions.create(
            model=settings.gemini_model,
            input=payload.prompt,
            system_instruction=(
                "You are the AI assistant inside a production starter application. "
                "Be concise, practical, and use plain text unless structure helps."
            ),
            generation_config={"temperature": payload.temperature},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini could not complete the request.",
        ) from exc

    text = getattr(interaction, "output_text", None)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini returned an empty response.",
        )
    return GenerateResponse(text=text, model=settings.gemini_model)
