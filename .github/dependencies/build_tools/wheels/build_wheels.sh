#!/bin/bash

set -e
set -x

export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)
export PYTHONHASHSEED=0

# Install pipx if not available (for PEP 668 workaround)
if [[ $(uname) == "Darwin" ]]; then
    brew install pipx 2>/dev/null || true
    pipx ensurepath
    export PATH="$HOME/.local/bin:$PATH"
fi

# OpenMP is not present on macOS by default
if [[ $(uname) == "Darwin" ]]; then
    if [[ "$CIBW_BUILD" == *-macosx_arm64 ]]; then
        if [[ $(uname -m) == "x86_64" ]]; then
            export PYTHON_CROSSENV=1
        fi
        export MACOSX_DEPLOYMENT_TARGET=13.0
        
        echo "Detected ARM64 architecture, installing libomp from Homebrew..."
        
        if [[ -n "$GITHUB_ACTIONS" ]]; then
            export PATH="/opt/homebrew/bin:$PATH"
        fi
        
        brew update || true
        brew install libomp
        
        if [[ -d "/opt/homebrew/opt/libomp" ]]; then
            PREFIX="/opt/homebrew/opt/libomp"
        elif [[ -d "/usr/local/opt/libomp" ]]; then
            PREFIX="/usr/local/opt/libomp"
        else
            echo "ERROR: libomp not found"
            exit 1
        fi
        
        export CC=/usr/bin/clang
        export CXX=/usr/bin/clang++
        export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
        export CFLAGS="$CFLAGS -I$PREFIX/include"
        export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
        export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
        
    else
        export MACOSX_DEPLOYMENT_TARGET=10.9
        echo "Detected Intel architecture, installing libomp from Homebrew..."
        brew update || true
        brew install libomp
        PREFIX="/usr/local/opt/libomp"
        
        export CC=/usr/bin/clang
        export CXX=/usr/bin/clang++
        export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
        export CFLAGS="$CFLAGS -I$PREFIX/include"
        export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
        export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
    fi
fi

if [[ "$GITHUB_EVENT_NAME" == "schedule" || "$CIRRUS_CRON" == "nightly" ]]; then
    export CIBW_BUILD_FRONTEND='pip; args: --pre --extra-index-url "https://pypi.anaconda.org/scientific-python-nightly-wheels/simple"'
fi

# Use pipx to install build tools (bypasses PEP 668)
if [[ $(uname) == "Darwin" ]]; then
    pipx install setuptools wheel twine 2>/dev/null || pip3 install --user setuptools wheel twine
else
    pip3 install setuptools wheel twine
fi

python3 setup.py clean build sdist bdist_wheel