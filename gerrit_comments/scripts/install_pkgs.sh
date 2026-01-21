#!/bin/bash

# Install Python dependencies using uv
uv pip install -r requirements.txt

# Install the gerrit_comments package in editable mode
uv pip install -e .

exit 0
