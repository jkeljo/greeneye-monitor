#!/bin/bash -ex

cd "$( dirname "${BASH_SOURCE[0]}" )"

virtualenv -p python3.5 --prompt '(greeneye-monitor) ' venv
source venv/bin/activate
pip3 install -r requirements.txt

echo Run source venv/bin/activate to work within the virtual environment
