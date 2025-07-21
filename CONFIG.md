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
```

This is the example Email route that reads incoming mail, summarizes it and messages the summary to the user using Matrix.

### Keys

#### name

Arbitrary name for the route - this is used for logging.

#### schedule_seconds

How often the scheduler should check for new input

#### prompt

A prompt to give to the processor. Note that each processor can alter the prompt on demand.

#### inputs

The list of modules that should be checked for input. You can use multiple inputs per route.

#### processors

The list of processors to run the input through. Each processor consists of a module and a list of tools that are provided to the module.
In case of the "Email Summaries" route it is advisable to leave the tools array empty since tools can execute code depending on their input.
You can use multiple processors. In that case each processor can alter the input data and the prompt.

#### outputs

The list of Output Modules. You can use multiple outputs.