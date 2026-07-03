import httpx
import urllib.parse
import logging
import asyncio

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"

QUALITY_SUFFIX = "highly detailed, masterpiece, sharp focus, 8k resolution, perfect anatomy, professional illustration"
ANIME_SUFFIX = "anime style, manga style, cel shading, vibrant colors, clean lineart, perfect hands"


async def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> bytes | None:
    try:
        person_keywords = [
            "girl", "boy", "woman", "man", "person", "character",
            "девушка", "парень", "человек", "персонаж", "женщина", "мужчина",
            "девочка", "мальчик", "warrior", "samurai", "ninja"
        ]
        if any(w in prompt.lower() for w in person_keywords):
            full_prompt = f"{prompt}, {ANIME_SUFFIX}, {QUALITY_SUFFIX}"
        else:
            full_prompt = f"{prompt}, {QUALITY_SUFFIX}"

        url = (
            f"{POLLINATIONS_URL}/{urllib.parse.quote(full_prompt)}"
            f"?nologo=true&width={width}&height={height}&model=flux&safe=false&seed={__import__('random').randint(1, 999999)}"
        )

        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.content
            logging.error(f"Image gen error: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Image gen error: {e}")
        return None


async def translate_to_english(prompt: str, gemini_client, model: str) -> str:
    try:
        from google.genai import types
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(
                text=f"Translate to English, return only translation: {prompt}"
            )])]
        )
        result = (response.text or "").strip()
        return result if result else prompt
    except:
        return prompt