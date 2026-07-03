import httpx
from bs4 import BeautifulSoup
import asyncio
import logging
import re

async def read_url(url: str) -> str:
    """Читает содержимое любой страницы"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return f"Не смогла открыть страницу (код {response.status_code})"

            soup = BeautifulSoup(response.text, "lxml")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "ads"]):
                tag.decompose()

            title = soup.title.string if soup.title else ""
            text = soup.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 40]
            content = "\n".join(lines[:80])

            result = f"Заголовок: {title}\n\n{content}"
            return result[:4000]

    except Exception as e:
        logging.error(f"URL read error: {e}")
        return f"Не смогла прочитать страницу: {e}"


async def read_youtube(url: str) -> str:
    """Читает YouTube видео — субтитры и информацию"""
    try:
        # Извлекаем video_id
        patterns = [
            r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})',
        ]
        video_id = None
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break

        if not video_id:
            return "Не смогла определить ID видео"

        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

        result_parts = []

        # Пробуем получить субтитры
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            transcript = None
            # Сначала пробуем русские
            try:
                transcript = transcript_list.find_transcript(['ru'])
            except:
                pass

            # Потом английские с переводом
            if not transcript:
                try:
                    transcript = transcript_list.find_transcript(['en'])
                except:
                    # Берём что есть
                    try:
                        transcript = transcript_list.find_generated_transcript(['ru', 'en'])
                    except:
                        pass

            if transcript:
                data = transcript.fetch()
                text = " ".join([entry['text'] for entry in data])
                # Обрезаем до разумного размера
                text = text[:3000]
                result_parts.append(f"Субтитры/транскрипция:\n{text}")

        except (NoTranscriptFound, TranscriptsDisabled):
            result_parts.append("Субтитры недоступны для этого видео")
        except Exception as e:
            result_parts.append(f"Субтитры: не удалось получить ({e})")

        # Получаем базовую инфу через yt-dlp
        try:
            import subprocess
            cmd = [
                "python3", "-c",
                f"""
import yt_dlp
ydl_opts = {{'quiet': True, 'no_warnings': True}}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info('https://www.youtube.com/watch?v={video_id}', download=False)
    print('TITLE:', info.get('title', ''))
    print('CHANNEL:', info.get('uploader', ''))
    print('VIEWS:', info.get('view_count', ''))
    print('DURATION:', info.get('duration', ''))
    print('DESCRIPTION:', (info.get('description', '') or '')[:500])
"""
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            if stdout:
                info_text = stdout.decode('utf-8', errors='ignore')
                result_parts.insert(0, f"Информация о видео:\n{info_text}")
        except Exception as e:
            logging.error(f"yt-dlp error: {e}")

        if not result_parts:
            return "Не смогла получить информацию о видео"

        return "\n\n".join(result_parts)[:4000]

    except Exception as e:
        logging.error(f"YouTube read error: {e}")
        return f"Ошибка при чтении YouTube: {e}"


async def process_url(url: str) -> str:
    """Определяет тип URL и вызывает нужный обработчик"""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    if "youtube.com" in url or "youtu.be" in url:
        return await read_youtube(url)
    else:
        return await read_url(url)