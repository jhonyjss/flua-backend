"""Generate image — port of generate-image.post.ts."""
from __future__ import annotations

import uuid

import httpx

from app.core.config import get_settings
from app.schemas.ai import GenerateImageRequest, GenerateImageResult
from app.services.replicate_client import generate_image_url


async def _upload_to_supabase(data: bytes, ext: str) -> str | None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    path = f"ai-generated/{uuid.uuid4().hex}.{ext}"
    url = f"{settings.supabase_url}/storage/v1/object/room-assets/{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            url,
            content=data,
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": f"image/{ext}",
            },
        )
    if res.status_code not in (200, 201):
        return None
    return f"{settings.supabase_url}/storage/v1/object/public/room-assets/{path}"


async def generate_image(req: GenerateImageRequest) -> GenerateImageResult:
    settings = get_settings()
    if not settings.replicate_api_key:
        return GenerateImageResult(success=False, error="REPLICATE_API_KEY not configured")

    quality = req.quality or ("hd" if req.type == "background" else "fast")
    use_flux = quality in ("hd", "4k")
    if quality == "4k":
        width, height = req.width or 1920, req.height or 1080
    elif quality == "hd":
        width, height = req.width or 1280, req.height or 720
    else:
        width = req.width or (1024 if req.type == "background" else 512)
        height = req.height or (576 if req.type == "background" else 512)

    try:
        image_url = await generate_image_url(
            req.prompt,
            width=width,
            height=height,
            style=req.style,
            use_flux=use_flux,
        )
    except Exception as exc:
        return GenerateImageResult(success=False, error=str(exc))

    storage_url = image_url
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            img_res = await client.get(image_url)
            img_res.raise_for_status()
            uploaded = await _upload_to_supabase(img_res.content, "webp")
            if uploaded:
                storage_url = uploaded
    except Exception:
        pass

    return GenerateImageResult(success=True, imageUrl=image_url, storageUrl=storage_url)
