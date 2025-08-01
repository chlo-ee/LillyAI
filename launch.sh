# /bin/bash

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python3 -m ensurepip --upgrade
python3 -m pip install -r requirements.txt
python3 -m LillyAI