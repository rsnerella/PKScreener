#!/bin/bash

set -e
set -x

export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)
export PYTHONHASHSEED=0

# Function to install Python packages safely on macOS
install_python_package() {
    local package=$1
    if [[ $(uname) == "Darwin" ]]; then
        # Try different installation methods
        if pip3 install --user --break-system-packages "$package" 2>/dev/null; then
            echo "Installed $package with --user --break-system-packages"
        elif pip3 install --user "$package" 2>/dev/null; then
            echo "Installed $package with --user"
        elif python3 -m pip install --user "$package" 2>/dev/null; then
            echo "Installed $package with python3 -m pip --user"
        else
            echo "WARNING: Could not install $package, continuing anyway"
        fi
    else
        pip3 install "$package"
    fi
}

# Install pipx using Homebrew properly
if [[ $(uname) == "Darwin" ]]; then
    # Reinstall pipx without breaking system
    brew uninstall --ignore-dependencies pipx 2>/dev/null || true
    brew install pipx
    
    # Ensure pipx path is set
    pipx ensurepath 2>/dev/null || true
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
        
        # Update Homebrew but ignore lock errors
        brew update 2>/dev/null || true
        
        # Install libomp, force if necessary
        brew install libomp 2>/dev/null || brew upgrade libomp 2>/dev/null || true
        
        # Find libomp installation
        if [[ -d "/opt/homebrew/opt/libomp" ]]; then
            PREFIX="/opt/homebrew/opt/libomp"
        elif [[ -d "/usr/local/opt/libomp" ]]; then
            PREFIX="/usr/local/opt/libomp"
        else
            echo "WARNING: libomp not found, attempting to continue without it"
            PREFIX=""
        fi
        
        if [[ -n "$PREFIX" ]]; then
            export CC=/usr/bin/clang
            export CXX=/usr/bin/clang++
            export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
            export CFLAGS="$CFLAGS -I$PREFIX/include"
            export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
            export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
        fi
        
    else
        export MACOSX_DEPLOYMENT_TARGET=10.9
        echo "Detected Intel architecture, installing libomp from Homebrew..."
        brew update 2>/dev/null || true
        brew install libomp 2>/dev/null || brew upgrade libomp 2>/dev/null || true
        PREFIX="/usr/local/opt/libomp"
        
        if [[ -d "$PREFIX" ]]; then
            export CC=/usr/bin/clang
            export CXX=/usr/bin/clang++
            export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
            export CFLAGS="$CFLAGS -I$PREFIX/include"
            export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
            export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
        fi
    fi
fi

if [[ "$GITHUB_EVENT_NAME" == "schedule" || "$CIRRUS_CRON" == "nightly" ]]; then
    export CIBW_BUILD_FRONTEND='pip; args: --pre --extra-index-url "https://pypi.anaconda.org/scientific-python-nightly-wheels/simple"'
fi

# Install build tools using the safe function
install_python_package "setuptools"
install_python_package "wheel"
install_python_package "twine"
install_python_package "build"

# Try different Python commands to find one that works
if command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

echo "Using Python command: $PYTHON_CMD"

# Clean and build
$PYTHON_CMD setup.py clean 2>/dev/null || true

# Try building with different methods
if ! $PYTHON_CMD setup.py build sdist bdist_wheel 2>/dev/null; then
    echo "First build attempt failed, trying with python -m build..."
    
    # Try using build module
    if $PYTHON_CMD -m build --sdist --wheel 2>/dev/null; then
        echo "Build with python -m build succeeded"
    else
        echo "Both build methods failed, attempting with pip wheel..."
        
        # Final attempt: use pip wheel
        $PYTHON_CMD -m pip wheel --no-deps --wheel-dir=dist . 2>/dev/null || {
            echo "ERROR: All build methods failed"
            exit 1
        }
    fi
fi

echo "Build completed successfully!"
ls -la dist/