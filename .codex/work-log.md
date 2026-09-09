# Project work log

## Objective

Rebuild the Discord game guide bot around SQLite and local Ollama, with structured factual queries, semantic guide retrieval, and per-user conversation memory.

## Current status

Complete. `/forget` deletes all stored messages for the requesting Discord user without affecting any other user's memory.

## Completed

- Replaced the Dify entry point with `skycity_bot.discord_bot.run`.
- Added settings, SQLite storage, Ollama client, structured/semantic knowledge, assistant orchestration, Discord routing, and a knowledge indexing command under `skycity_bot/`.
- Added canonical structured pet facts in `knowledge/structured.yaml`.
- Added initial knowledge and storage tests.
- Added the personal `continuous-work-log` Skill and this persistent log.
- Installed all packages from `requirements.txt` into `.venv`.
- Downloaded `nomic-embed-text-v2-moe` through Ollama.
- Copied 13 supplied `.txt` knowledge files into `knowledge/documents` and indexed them as 18 chunks in `data.db`.
- Added `python -m skycity_bot.ask` for testing without Discord or a Discord token.
- Added deterministic SQLite answers for recognized pet type, L tier, and growth questions.
- Limited retrieved context to 3500 characters to stay within the local model's context budget.
- Restored the legacy `/setPass` role and channel rules after comparison with the original code.
- Confirmed the active ignored `config.yaml` enables channel limiting for `1210695777169711187` and `714725643765415958`; no secret values were read or changed.
- Added `/forget` routing through the assistant to SQLite memory deletion, scoped by Discord user ID across guilds.

## Decisions and constraints

- Run every terminal command through `cmd.exe`.
- Run Python with `.\.venv\Scripts\python.exe`.
- Install packages with `.\.venv\Scripts\pip3.exe install ...`.
- Use SQLite for all SQL persistence.
- Use Ollama with `qwen3.5:4b` as the local chat model.
- Keep exact game facts in structured tables and use semantic retrieval for prose guides.
- Key conversation history by Discord guild and user.
- Preserve the existing Discord commands and behavior where practical.

## Validation

- On 2026-09-09, `ollama ps` responded successfully, confirming the Ollama service is running; its empty model table means no model is currently loaded in memory.
- Ollama previously reported `qwen3.5:4b` running with 100% GPU.
- The `continuous-work-log` Skill passes `quick_validate.py`.
- `.\.venv\Scripts\python.exe` reports Python 3.11.9 and `test.py` prints `Hello, World!` when the tool is allowed to read the base Python under AppData. The earlier failure was caused by workspace sandbox permissions, not a broken environment.
- `compileall` completes successfully for the bot package and tests.
- The first test run executed five tests; all errors were Windows cleanup failures caused by an open SQLite engine, rather than failed feature assertions.
- After adding `Database.close()`, all five unit tests pass.
- A live `qwen3.5:4b` tool-call smoke test answered that item-shop pets stop at L4 and did not substitute the shop-pet L5 value.
- The suite now includes a sixth regression test for deterministic invalid-tier answers.
- The local exact query returns that item-shop pets stop at L4 and omits the shop-pet L5 value 3.7.
- A semantic new-player query returned a grounded answer from the indexed documents without truncation after the context cap was added.
- Final `compileall`, all six unit tests, Skill validation, and `git diff --check` pass.
- No temporary diagnostic scripts remain. The user-created `test.py` remains untouched.
- The suite now has seven passing tests, including enforcement of the two configured Discord channel IDs.
- The suite now has eight passing tests, including `/forget` deletion across guilds and preservation of other users' history.

## Blockers

- None currently.

## Next steps

1. Start the bot with `.\.venv\Scripts\python.exe bot.py` when ready.
2. Re-run `.\.venv\Scripts\python.exe -m skycity_bot.index_knowledge` whenever source documents change.
