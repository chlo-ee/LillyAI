import paho.mqtt.client as mqtt

config = {}
client = None
tool_function = 'set_light'

def get_client():
    global client
    if client is None:
        unacked_publish = set()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.user_data_set(unacked_publish)
        client.connect(host=config["mqtt_broker"], port=config["mqtt_port"])
        client.loop_start()
    return client


def get_tooling():
    light_names = []
    for light in config["lights"]:
        light_names.append(light["name"])
    tool = {
        "type": "function",
        "function": {
            "name": tool_function,
            "description": "Turn the light on or off",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "The room to switch the light in",
                        "enum": light_names
                    },
                    "state": {
                        "type": "string",
                        "description": "Whether the light should be on or off",
                        "enum": ["on", "off"]
                    }
                },
                "required": ["room", "state"]
            }
        }
    }

    return tool

def run_tool(parameters):
    try:
        room = parameters["room"]
        state = parameters["state"]

        light = None
        for cfg_light in config["lights"]:
            if cfg_light["name"] == room:
                light = cfg_light

        topic = light["topic"]
        payload = light["commands"][state]
        get_client().publish(topic, payload)
    except:
        return "Lights could not be set."
    return "Lights set."


if __name__ == "__main__":
    print('This module is part of LillyAI and can not be run individually.')