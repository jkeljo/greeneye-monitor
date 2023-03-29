#!/bin/bash -ex

cd "$( dirname "${BASH_SOURCE[0]}" )"

pyenv install -s 3.10.7
pyenv virtualenv 3.10.7 greeneye-monitor
pyenv local greeneye-monitor
pip3 install --upgrade pip
pip3 install -r requirements.txt
