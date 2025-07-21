# LillyAI

## What is LillyAI

LillyAI has been my dream project since I was a child.
An AI assistant that could basically take control over whatever you would like.
Only now have LLMs become powerful enough to achieve this.

LillyAI is a modular approach to AI assistants. You want Lilly to read your mail?
Sure - just make sure the "Email"-Module is loaded and a route is set up for it.
You want Lilly to control your lights?
No problem, just make sure the AI model has access to the "MQTTLights" module.

## What makes Lilly so cool?

Lilly is ultra context-aware.
For example when she summarized an incoming Email you can absolutely ask her about some specifics in that Email.
Lilly remembers everything in an sqlite-Database. Just... make sure nobody steals this one ;)

## Prerequisites

There are a few things required in order for LillyAI to work:

### Python3 with pip

This should be pretty straightforward. But in order to install this you will need a not-insanely-old version of Python3. 
You will also need pip - this is usually provided with the repositories of your Linux.
If you are using Windows or for some reason do not have a package manager with pip, you can do this:

```commandline
python -m ensurepip --upgrade
```

### Ollama instance

Right now we only support Ollama as AI processor.
So in order to use LillyAI you will have to provide it with a running Ollama instance.
Here is an example on running Ollama and installing qwen3:14b (used in the example config):

```commandline
ollama serve
ollama pull qwen3:14b
```

Note that if you are running Ollama anywhere else but on localhost, you will also need to set the "OLLAMA_HOST" environment variable to "0.0.0.0".

## Installation

Installing LillyAI isn't too hard. Just clone the repo, set up a virtual environment and install the requirements:

```commandline
git clone https://github.com/chlo-ee/LillyAI
cd LillyAI
python -m venv .venv
source .venv/bin/actiavte
python -m pip install -r requirements.txt
```

If you are using a Linux system you can also run the launch.sh script.
This will create and activate the venv automatically and also install all requirements:

```commandline
git clone https://github.com/chlo-ee/LillyAI
cd LillyAI
./launch.sh
```

Be aware that this will fail if you don't have a configuration yet!

### Optional: Systemd Service

You can also use the systemd service file provided here to automatically start Lilly on boot.
It is strongly recommended that you create a system user for this - the default is "lilly".

Example installation for Arch Linux:

```commandline
sudo useradd -s /bin/nologin -d /opt/LillyAI --no-create-home --system lilly
git clone https://github.com/chlo-ee/LillyAI
sudo mv LillyAI /opt
sudo chown -R lilly /opt/LillyAI
sudo cp /opt/LillyAI/lilly.service /etc/systemd/system/lilly.service
sudo systemctl daemon-reload
sudo systemctl enable lilly
```

You can then start Lilly manually using:

```commandline
sudo systemctl start lilly
```

## Configuration

Configuration is done via the config.json. You can use the example.config.json as a baseline for this:

```commandline
cp example.config.json config.json
edit config.json
```

For more information on the config values see [Configuration](./CONFIG.md)

## Running LillyAI

Running LillyAI is also pretty simple:

```commandline
source .venv/bin/actiavte
python -m LillyAI 
```

## Modules

There are four roles each module can have. Note that each module can have several roles.

### Input Modules

Those are modules that load input from a source.
This might be an Email client reading incoming mail or a Matrix client waiting for the user to chat.

### Processor Modules

Processor Modules are mostly LLMs.
They take the input from the input module and sometimes mix it with a prompt provided by the route.
They then process it - for example by interrogating an LLM - and output the result.
Furthermore, they can also alter the prompt which means that multiple LLMs could be chained together.

### Tool Modules

A Tool is something an LLM can use to improve its output.
Basically it provides an interface for the LLM to execute code and read the result.
Tools can also be used to just execute things like home automation tasks.
These modules can be provided to each processor individually.

### Output Modules

Output Modules are pretty simple.
They take the result from the processor modules and output it.
An example would be sending message via Matrix.

## Routes

Routes define the way information travels through Lilly.
A route will have at least one Input Module.
The input is then forwarded to all the Processor Modules of the route.
The route may also add a prompt to let the processor know what to do with the data.
The Processor Modules may also be given access to Tool Modules as described above.
Then the output from the Processor Modules is forwarded to at least one Output Module.

### Example

One of the default routes is the Email Summary route:

```
+-------+      +------------+      +--------+
| Input |      | Processors |      | Output |
| ===== |  =>  | ========== |  =>  | ====== |
| Email |      | Ollama     |      | Matrix |
+-------+      |  Tools:    |      +--------+
               |   * None   |
               +------------+
```

Note that this route does not feature any tools as it can be triggered by third parties and tools can execute code.

The chatbot from the example looks like this:

```
+--------+      +----------------+      +--------+
| Input  |      |   Processors   |      | Output |
| ====== |  =>  | ============== |  =>  | ====== |
| Matrix |      | Ollama         |      | Matrix |
+--------+      |  Tools:        |      +--------+
                |   * MQTTLights |
                +----------------+
```

This route does feature the MQTTLights tool which can toggle lights via MQTT.
Also note that in this case "Matrix" is the input as well as the output module as modules can feature different roles.

## Security implications

Obviously this lets you give LLMs control over whatever you want.
An incoming Email could for example contain malicious information that an LLM might "fall" for.
This is why it's generally recommended to never use tools with an Input Module that processes potentially harmful contents.

## Missing stuff

The modular nature of LillyAI make her pretty easily extensible.
There are however a few things that are still missing from the core.

### Route verification

Right now routes are simply loaded on start.
If you set an Output-only Module as Input Module, it will only crash once Lilly tries to access the input.
Routes can easily be verified and I will add this soon.

### Better logging

Logging is pretty sparse right now. Config errors also just result in crashes. We can and should fix this

### Shutdown routine

Shutdowns are pretty much done using SIGKILL right now. This is stupid and will be fixed soon.
