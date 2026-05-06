#!/bin/bash

set -e
set -x

# Set environment variables for reproducible builds
export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)
export PYTHONHASHSEED=0

# For macOS, set the deployment target
if [[ $(uname) == "Darwin" ]]; then
    if [[ "$CIBW_BUILD" == *-macosx_arm64 ]]; then
        export MACOSX_DEPLOYMENT_TARGET=13.0
    else
        export MACOSX_DEPLOYMENT_TARGET=10.9
    fi
fi

# Install cibuildwheel if not already installed
if ! command -v cibuildwheel &> /dev/null; then
    pip3 install cibuildwheel
fi

# Build wheels using cibuildwheel
python3 -m cibuildwheel --output-dir dist

# Also build source distribution
pip3 install setuptools wheel
python3 setup.py clean build sdist