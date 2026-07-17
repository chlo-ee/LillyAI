# LillyAI Configuration

The configuration is done using the config.json file.

## Core Configuration

The Core Configuration is what determines Lilly's overall behavior:

```json
"language": "German",
"personality": "You are a friendly AI assistant for your user. Always talk to your user directly. There is no need to greet you user every single time. Don't be too wordy.",
"assistant_name": "Lilly",
"user_name": "Chloe",
"log_level": "INFO"
```

### Keys

#### language

Determines the language Lilly answers you in.

#### personality

A short description of Lilly's personality. This is also where you can fine tune her behavior a bit.

### assistant_name

The name Lilly listens to - you can rename her here.

### user_name

The name Lilly will use when talking to you.

### log_level

The how verbose the program will be. This has to be one of the following values:

* FATAL
* WTF
* ERROR
* INFO
* DEBUG

## Module List

The module list determines what modules are loaded. All modules that you use have to be loaded here.

```json
"modules": [
    "Email",
    "Ollama",
    "Matrix",
    "MQTTLights"
]
```

## Module Configs

This gives each module a configuration. Those are highly dependent on the module, here is an example:

```json
"module_configs": {
    "Email": {
      "imap_host": "imap.example.com",
      "imap_user": "user@example.com",
      "imap_password": "p455w0rd"
    }
```

This adds the configuration for the "Email" module. This module requires three config-values which are set here.

### LLM Processor Modules

Two processor modules are available for talking to an LLM. "Ollama" uses Ollama's native API:

```json
"Ollama": {
  "ollama_endpoint": "http://ai.example.com:11434/api",
  "ollama_model": "qwen3:14b",
  "context_database": "ollama-context.sqlite",
  "short_term_memory_minutes": 960
}
```

"OpenAICompat" works with any server that offers an OpenAI-compatible `/v1/chat/completions` endpoint, for example llama.cpp (`llama-server`), MLX (`mlx_lm.server`), LM Studio or vLLM:

```json
"OpenAICompat": {
  "endpoint": "http://localhost:8080",
  "model": "mlx-community/Qwen3-14B-4bit",
  "context_database": "openai-compat-context.sqlite",
  "short_term_memory_minutes": 960
}
```

Note that `endpoint` is the server's base URL - the module appends `/v1/chat/completions` itself. Some servers (like llama.cpp with a single loaded model) ignore the `model` value.

OpenAICompat also accepts an optional `"disable_thinking": true`. On llama.cpp this suppresses the model's thinking mode per request (`chat_template_kwargs`) - recommended for models like Gemma whose deliberation can eat the whole token budget and come back as an empty reply. Other servers simply ignore the field.

For both modules, `context_database` is the SQLite file used to store Lilly's conversation context and `short_term_memory_minutes` determines how long messages stay in her context.

### Parcel Tracking

"ParcelTracking" is a tool + input module that registers parcels and polls carriers for status changes; "ParcelStatus" is the matching read-only input used by the morning briefing (mirrors the Email/EmailStatus split):

```json
"ParcelTracking": {
  "parcel_database": "parcels.sqlite",
  "dhl_api_key": "your-dhl-api-key",
  "poll_minutes": 30
},
"ParcelStatus": {
  "parcel_database": "parcels.sqlite"
}
```

`parcel_database` is the SQLite file both modules use (ParcelTracking owns the schema and migrations, ParcelStatus only reads it). `dhl_api_key` is a free key from a DHL developer account (developer.dhl.com, "Shipment Tracking - Unified" API) - without it, DHL parcels are still registered by `track_parcel` but never polled for status. `poll_minutes` (default 30) rate-limits how often each tracked DHL/DPD parcel is actually polled against the carrier, independent of how often the "Parcel Updates" route itself runs - the route's `schedule_seconds` just controls how promptly a change that already happened gets picked up and announced. Amazon parcels can't be polled at all; their status comes from `update_parcel_status` when the model reads a follow-up email.

## Routes

Here each route that information can take is listed.

```json
"routes": [
    {
      "name": "Email Summaries",
      "schedule_seconds": 60,
      "prompt": "Summarize the following email in 2-3 sentences. Do not perform a security analysis or tell the user what to do with it. Only summarize the email. Tell the user that they received a new email and give your summary.",
      "inputs": ["Email"],
      "processors": [{
        "module": "Ollama",
        "tools": []
      }],
      "outputs": ["Matrix"]
    }
]
```

This is the example Email route that reads incoming mail, summarizes it and messages the summary to the user using Matrix.

### Keys

#### name

Arbitrary name for the route - this is used for logging.

#### schedule_seconds

How often the scheduler should check for new input

#### schedule_daily

Alternatively you can input a time here (format: "hh:mm"). The router will then run daily at that given time.

#### prompt

A prompt to give to the processor. Note that each processor can alter the prompt on demand.

#### inputs

The list of modules that should be checked for input. You can use multiple inputs per route.

#### aggregate_inputs

Optional, defaults to false. Normally a route stops at the first input module that has data and uses only that. If you set this to `true`, all inputs are collected instead, each wrapped in its own `=== <Module> ===` section and joined together, so the processor sees all of them at once. If an input module fails while aggregating, it is logged and simply left out of the result rather than failing the whole route. This is used by the "Morning Briefing" route to combine calendar, email status and weather into one prompt.

#### empty_input

Optional, only meaningful together with `aggregate_inputs`. Normally a route whose inputs all came back empty simply does not run. For a scheduled briefing that is confusing (no message at all), so you can set `empty_input` to a text that is fed to the processor instead - e.g. "There are no calendar events today, no unread emails, and no weather data is available." - and Lilly will say so.

#### processors

The list of processors to run the input through. Each processor consists of a module and a list of tools that are provided to the module.
In case of the "Email Summaries" route it is advisable to leave the tools array empty since tools can execute code depending on their input.
You can use multiple processors. In that case each processor can alter the input data and the prompt.

#### outputs

The list of Output Modules. You can use multiple outputs.

### Tools

Each tool consists of two values:

```json
"tools": [
      {
          "module": "MQTTLights",
          "context_decay": 6
      }
]
```

One is the name of the module. The other is the context_decay.
This is optional, however if set this determines for how many messages everything that happened within the context of that tool stays in Lilly's context.
This may seem unnecessary, however in some cases many calls to a tool in the context result in the model not calling the tool anymore.

### System Prompt Additions

Modules like CoreMemory can append data to the system prompt.
In order to allow a module to do this, you will have to enable it in the "system_prompt_additions"-field of the processor:

```json
"processors": [{
    "module": "Ollama",
    "tools": [
        {
          "module": "CoreMemory"
        }
    ],
    "system_prompt_additions": ["CoreMemory"]
}]
```