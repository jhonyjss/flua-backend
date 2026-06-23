"""Replicate image generation client."""
from __future__ import annotations

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client


STYLE_PROMPTS = {
    "realistic": "photorealistic, highly detailed, professional photography, 8k uhd",
    "anime": "anime style, vibrant colors, detailed anime art, studio ghibli inspired",
    "digital-art": "digital art, detailed illustration, artstation trending",
    "fantasy": "fantasy art, magical atmosphere, detailed fantasy illustration, epic lighting",
    "cinematic": "cinematic lighting, movie scene, dramatic atmosphere, film grain, 4k cinematic",
}


def _aspect_ratio(width: int, height: int) -> str:
    ratio = width / height if height else 1.0
    if 1.7 <= ratio <= 1.8:
        return "16:9"
    if 1.3 <= ratio <= 1.4:
        return "4:3"
    if 0.7 <= ratio <= 0.8:
        return "3:4"
    if 0.55 <= ratio <= 0.6:
        return "9:16"
    return "16:9"


async def generate_image_url(
    prompt: str,
    *,
    width: int,
    height: int,
    style: str = "realistic",
    use_flux: bool = True,
) -> str:
    settings = get_settings()
    if not settings.replicate_api_key:
        raise HTTPException(500, "REPLICATE_API_KEY not configured")

    width = max(256, min(width, 1920 if use_flux else 1280))
    height = max(256, min(height, 1920 if use_flux else 1280))
    width -= width % 8
    height -= height % 8
    style_suffix = STYLE_PROMPTS.get(style, STYLE_PROMPTS["realistic"])
    full_prompt = f"{prompt}, {style_suffix}"

    if use_flux:
        version = "black-forest-labs/flux-schnell"
        input_payload = {
            "prompt": full_prompt,
            "aspect_ratio": _aspect_ratio(width, height),
            "num_outputs": 1,
            "output_format": "webp",
        }
    else:
        version = "bytedance/sdxl-lightning-4step"
        input_payload = {
            "prompt": full_prompt,
            "width": width,
            "height": height,
            "num_outputs": 1,
        }

    async with http_client(timeout=120.0) as client:
        create = await client.post(
            "https://api.replicate.com/v1/predictions",
            json={"version": version, "input": input_payload},
            headers={
                "Authorization": f"Token {settings.replicate_api_key}",
                "Content-Type": "application/json",
            },
        )
    if create.status_code not in (200, 201):
        raise HTTPException(502, f"Replicate error {create.status_code}: {create.text[:200]}")

    prediction = create.json()
    poll_url = prediction.get("urls", {}).get("get") or prediction.get("url")
    if not poll_url:
        raise HTTPException(502, "Replicate did not return poll URL")

    import asyncio

    for _ in range(60):
        async with http_client(timeout=30.0) as client:
            poll = await client.get(
                poll_url,
                headers={"Authorization": f"Token {settings.replicate_api_key}"},
            )
        if poll.status_code != 200:
            raise HTTPException(502, f"Replicate poll error {poll.status_code}")
        data = poll.json()
        status = data.get("status")
        if status == "succeeded":
            output = data.get("output")
            if isinstance(output, list) and output:
                return str(output[0])
            if isinstance(output, str):
                return output
            raise HTTPException(502, "Replicate returned empty output")
        if status in ("failed", "canceled"):
            raise HTTPException(502, f"Replicate generation {status}")
        await asyncio.sleep(2)

    raise HTTPException(504, "Replicate generation timed out")
