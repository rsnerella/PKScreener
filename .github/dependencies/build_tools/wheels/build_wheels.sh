#!/bin/bash

set -e
set -x

# Set environment variables to make our wheel build easier to reproduce byte
# for byte from source. See https://reproducible-builds.org/. The long term
# motivation would be to be able to detect supply chain attacks.
#
# In particular we set SOURCE_DATE_EPOCH to the commit date of the last commit.
#
# XXX: setting those environment variables is not enough. See the following
# issue for more details on what remains to do:
# https://github.com/scikit-learn/scikit-learn/issues/28151
export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)
export PYTHONHASHSEED=0

# OpenMP is not present on macOS by default
if [[ $(uname) == "Darwin" ]]; then
    # Make sure to use a libomp version binary compatible with the oldest
    # supported version of the macos SDK as libomp will be vendored into the
    # scikit-learn wheels for macos.

    if [[ "$CIBW_BUILD" == *-macosx_arm64 ]]; then
        if [[ $(uname -m) == "x86_64" ]]; then
            # arm64 builds must cross compile because the CI instance is x86
            # This turns off the computation of the test program in
            # sklearn/_build_utils/pre_build_helpers.py
            export PYTHON_CROSSENV=1
        fi
        # SciPy requires 12.0 on arm to prevent kernel panics
        # https://github.com/scipy/scipy/issues/14688
        # We use the same deployment target to match SciPy.
        export MACOSX_DEPLOYMENT_TARGET=13.0
        
        # For ARM64, we MUST use libomp from Homebrew (intel-openmp doesn't work)
        echo "Detected ARM64 architecture, installing libomp from Homebrew..."
        
        # Check if running on GitHub Actions runner
        if [[ -n "$GITHUB_ACTIONS" ]]; then
            echo "Running on GitHub Actions runner"
            # Homebrew on GitHub Actions ARM64 runner is at /opt/homebrew
            export PATH="/opt/homebrew/bin:$PATH"
        fi
        
        # Install libomp via Homebrew (skip pip entirely for ARM64)
        brew update || true
        brew install libomp
        
        # Set up paths for libomp
        if [[ -d "/opt/homebrew/opt/libomp" ]]; then
            PREFIX="/opt/homebrew/opt/libomp"
        elif [[ -d "/usr/local/opt/libomp" ]]; then
            PREFIX="/usr/local/opt/libomp"
        else
            echo "ERROR: libomp not found after brew install"
            exit 1
        fi
        
        echo "OpenMP found at: $PREFIX"
        export CC=/usr/bin/clang
        export CXX=/usr/bin/clang++
        export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
        export CFLAGS="$CFLAGS -I$PREFIX/include"
        export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
        export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
        
    else
        # Intel macOS (x86_64)
        export MACOSX_DEPLOYMENT_TARGET=10.9
        
        echo "Detected Intel architecture, trying pip intel-openmp with venv..."
        
        # Create a temporary venv for pip operations to avoid PEP 668 issues
        TEMP_VENV=$(mktemp -d)
        python3 -m venv "$TEMP_VENV"
        source "$TEMP_VENV/bin/activate"
        
        # Try to install intel-openmp via pip (faster, no brew dependency)
        if pip install intel-openmp 2>/dev/null; then
            echo "Successfully installed intel-openmp via pip"
            SITE_PACKAGES=$(python -c "import site; print(site.getsitepackages()[0])")
            echo "Site packages: $SITE_PACKAGES"
            
            if [ -f "$SITE_PACKAGES/intel_openmp/lib/libiomp5.dylib" ]; then
                PREFIX="$SITE_PACKAGES/intel_openmp"
            elif [ -f "$SITE_PACKAGES/lib/libiomp5.dylib" ]; then
                PREFIX="$SITE_PACKAGES"
            else
                echo "intel-openmp installed but library not found, falling back to brew"
                deactivate
                brew install libomp
                PREFIX="/usr/local/opt/libomp"
            fi
        else
            # Fallback to libomp from Homebrew
            echo "intel-openmp not available, falling back to libomp from Homebrew"
            deactivate
            brew install libomp
            PREFIX="/usr/local/opt/libomp"
        fi
        
        # Clean up temp venv
        rm -rf "$TEMP_VENV"

        export CC=/usr/bin/clang
        export CXX=/usr/bin/clang++
        export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
        export CFLAGS="$CFLAGS -I$PREFIX/include"
        export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
        export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
    fi

    echo "OpenMP environment configured:"
    echo "  PREFIX: $PREFIX"
    echo "  CFLAGS: $CFLAGS"
    echo "  LDFLAGS: $LDFLAGS"
fi


if [[ "$GITHUB_EVENT_NAME" == "schedule" || "$CIRRUS_CRON" == "nightly" ]]; then
    # Nightly build:  See also `../github/upload_anaconda.sh` (same branching).
    # To help with NumPy 2.0 transition, ensure that we use the NumPy 2.0
    # nightlies.  This lives on the edge and opts-in to all pre-releases.
    # That could be an issue, in which case no-build-isolation and a targeted
    # NumPy install may be necessary, instead.
    export CIBW_BUILD_FRONTEND='pip; args: --pre --extra-index-url "https://pypi.anaconda.org/scientific-python-nightly-wheels/simple"'
fi

# Install build dependencies using venv to avoid PEP 668 issues
if [[ $(uname) == "Darwin" ]] && [[ "$CIBW_BUILD" != *-macosx_arm64 ]]; then
    # For Intel macOS, we already have a venv or use system python with --user flag
    pip3 install --user setuptools wheel twine 2>/dev/null || pip3 install setuptools wheel twine
else
    # For ARM64 and other platforms, use regular pip (in CI environment)
    pip3 install setuptools wheel twine
fi

# Use python directly for setup commands
python3 -c "import setuptools; import wheel" 2>/dev/null || echo "Warning: Build tools may not be properly installed"

python3 setup.py clean build sdist bdist_wheel