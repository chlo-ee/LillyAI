# LillyAI — Claude Code Reference

> **Keep this file up to date.** Whenever you make changes that affect architecture, module interfaces, configuration, or development workflow, update the relevant sections here.

## Project Overview

LillyAI is a modular, event-driven AI assistant framework. It connects data sources (inputs) through an LLM (processor) to action handlers (tools) and delivery channels (outputs) via a configurable pipeline called a **route**. The AI persona is named "Lilly" and runs locally against an Ollama LLM endpoint.

## Tech Stack

- **Language**: Python 3 (async/await throughout)
- **LLM backend**: Ollama (native API) or any OpenAI-compatible server (llama.cpp, MLX, LM Studio, vLLM, …)
- **Persistence**: SQLite (context/memory per module)
- **Protocols**: IMAP (email), Matrix (chat), CalDAV (calendar), MQTT (IoT/lights)
- **Key deps**: `matrix-nio`, `IMAPClient`, `caldav`, `paho-mqtt`, `beautifulsoup4`, `markdown`

## Running the Project

```bash
# First-time setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp example.config.json config.json  # then fill in credentials

# Run
source .venv/bin/activate
python -m LillyAI

# Or via launch script
./launch.sh
```

Requires a running LLM server: either Ollama (`ollama serve`) with the configured model pulled, or any OpenAI-compatible server (e.g. `llama-server -m model.gguf`, `mlx_lm.server --model …`) when using the OpenAICompat module.

### Nix / NixOS

The repo is a flake:

- `nix run .# -- config.json` — run Lilly directly
- `packages.default` (`lillyai`), `packages.voice` (`lillyai-voice`)
- `nixosModules.default` — `services.lillyai` (config.json via LoadCredential, state in `/var/lib/lillyai`)
- `nixosModules.voice` — `services.lillyai-voice` (LillyVoice, env-file driven)

Deployed on the `lilly` host of the NixOS fleet (see the NixOS repo's `modules/nixos/lilly.nix`).

## Project Structure

```
LillyAI.py          # Entry point — loads modules, wires routes, starts scheduler
LillyVoice.py       # Standalone Matrix voice-memo bot (transcribe/summarise/draft)
flake.nix           # Nix flake: packages (lillyai, lillyai-voice) + NixOS modules
Router.py           # Routes class — validates & executes input→processor→output pipelines
Scheduler.py        # Interval and daily scheduling of routes
PromptTools.py      # Builds system prompts (name, language, personality)
Logging.py          # Custom logger with levels: FATAL, WTF, ERROR, INFO, DEBUG

Modules/            # One directory per module, named after the module
  <Name>/           # e.g. Email, Ollama, OpenAICompat, Matrix, CalDAV, …
    __init__.py     # Exposes MODULE_NAME, config and the role functions
    DBMigrations/   # Versioned SQL migrations (only for modules with persistence)
config.json         # Runtime config (gitignored — based on example.config.json)
example.config.json # Config template
CONFIG.md           # Detailed config documentation
README.md           # Project overview and installation guide
```

## Module Interface Contract

All modules must expose specific functions depending on their role:

| Role | Required function |
|------|------------------|
| Input | `async get_data()` |
| Processor | `process_data(data, prompt, tools, system_prompt_additions)` — returns `(data, prompt)` |
| Tool | `get_tooling()`, `run_tool(name, args)`, `tool_functions` list, optionally `get_system_prompt_content()` |
| Output | `async output(data)` |

Every module also exposes `MODULE_NAME` and a module-level `config` dict — the loader fills it from `module_configs` in `config.json` (config is not passed as a function argument).

New modules must implement the full interface for their role to be valid in a route.

## Route Configuration Pattern

A route defines a full pipeline in `config.json`:

```json
{
  "name": "Email Summaries",
  "schedule_seconds": 60,
  "inputs": ["Email"],
  "processors": [{
    "module": "Ollama",
    "tools": [{"module": "CalDAV"}],
    "system_prompt_additions": ["CoreMemory"]
  }],
  "outputs": ["Matrix"]
}
```

Routes take an optional `"aggregate_inputs": true` — then ALL inputs are collected into one labelled text block (`=== <Module> ===` sections; failing inputs are logged and skipped) instead of the default first-non-empty-input behaviour; used by the Morning Briefing route.

## Key Architectural Notes

- **Context management**: `ContextManager` stores message history in SQLite with configurable decay (minutes). Tool call context can decay faster than regular context via `context_decay` on tool configs.
- **Tool calling loop**: `OllamaInstance`/`OpenAICompatInstance` handle multi-turn tool use — they keep calling tools until the LLM stops requesting them.
- **DB migrations**: Each module with persistence manages its own versioned migrations under `Modules/<Name>/DBMigrations/`.
- **Async, mostly**: Input and output module functions are `async`. Processor and tool calls are currently synchronous and block the event loop while the LLM generates.
- **One instance per module**: Module config is a module-level singleton, so e.g. only one `OpenAICompat` endpoint can be configured at a time.

## Current Modules

### Inputs
- **Email** — reads unread IMAP emails, parses HTML/plain text
- **Weather** — today's forecast via open-meteo (no API key)
- **EmailStatus** — unread-mail count + subjects (peek only, nothing marked read)
- **Matrix** — listens for DMs in Matrix chat
- **CalDAV** — retrieves upcoming calendar events
- **Timing** — triggers routes based on scheduled timed events

### Processors
- **Ollama** — queries local Ollama LLM via its native API; manages context and tool-calling loop
- **OpenAICompat** — queries any OpenAI-compatible server (`/v1/chat/completions`): llama.cpp, MLX (`mlx_lm.server`), LM Studio, vLLM, …; same context and tool-calling loop as Ollama

### Tools
- **CalDAV** — `get_calendar_events`, `add_calendar_event`
- **CoreMemory** — `store_memory` (SQLite-backed persistent memory)
- **MQTTLights** — `set_light` (MQTT-based light control)
- **Timing** — `schedule_event` (schedule future LillyAI actions)
- **WebSearch** — `search_web` (live web search via a SearXNG instance's JSON API)
- **Messenger** — `compose_message` (files a compose request; LillyVoice drafts it in the user's voice, 👍 in the drafts room sends it)

### Outputs
- **Matrix** — sends Markdown-rendered responses via Matrix chat

## LillyVoice (standalone service)

`LillyVoice.py` is a separate long-running service (`python -m LillyVoice`), not a route module — voice memos need room-scoped routing, audio chunking (ffmpeg → ≤28s WAV → multimodal llama.cpp) and E2EE, which don't fit the text-pipeline architecture. It syncs as the *user's* account (bridge portals reject foreign bots), transcribes + summarises voice memos in bridged chats, drafts replies in the user's voice into an unbridged drafts room, and relays a draft out when the user reacts 👍. When `MATRIX_LILLY_USER_ID`/`MATRIX_LILLY_TOKEN` are set, drafts and notices are posted by Lilly's own account instead. Config is all environment variables — see the module docstring.
