"""Report prompt block sizes and history tokens for a voice command."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from sakura_core.llm import _build_contents, get_client
from sakura_core.prompt import _build_system


async def main() -> None:
    query = "сделай громче"
    system_blocks: list[str] = []
    system = await _build_system(query=query, blocks_out=system_blocks)

    print(f"Системный промпт: {len(system)} символов, блоков: {len(system_blocks)}")
    for index, block in enumerate(system_blocks, start=1):
        first_line = next((line.strip() for line in block.splitlines() if line.strip()), "пустой блок")
        print(f"  {index:02d}. {first_line[:80]} — {len(block)} символов")

    contents = _build_contents(
        query, history_limit=config.VOICE_HISTORY_LIMIT
    )
    client = get_client(config.get_active_key())
    token_count = client.models.count_tokens(
        model="gemma-4-31b-it", contents=contents
    )
    print(
        f"История и запрос: {token_count.total_tokens} токенов "
        f"(лимит истории: {config.VOICE_HISTORY_LIMIT}, сообщений: {len(contents)})"
    )


if __name__ == "__main__":
    asyncio.run(main())