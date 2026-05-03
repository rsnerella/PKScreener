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
    else
        export MACOSX_DEPLOYMENT_TARGET=10.9
    fi

    # Alternative: Install OpenMP via pip (intel-openmp)
    # This is more reliable in CI environments without conda
    echo "Installing OpenMP via pip..."
    pip3 install intel-openmp
    
    # For ARM64, we also need the specific wheel
    if [[ "$CIBW_BUILD" == *-macosx_arm64 ]]; then
        pip3 install --no-deps intel-openmp
    fi
    
    # Set up paths for OpenMP from pip installation
    SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])")
    echo "Site packages: $SITE_PACKAGES"
    
    # Find OpenMP library
    if [ -f "$SITE_PACKAGES/intel_openmp/lib/libiomp5.dylib" ]; then
        PREFIX="$SITE_PACKAGES/intel_openmp"
        echo "OpenMP found in intel_openmp package"
    elif [ -f "$SITE_PACKAGES/lib/libiomp5.dylib" ]; then
        PREFIX="$SITE_PACKAGES"
        echo "OpenMP found in site packages lib"
    else
        # Try to find it
        find $SITE_PACKAGES -name "*iomp5*" -o -name "*libomp*" 2>/dev/null || true
        # Fall back to brew if pip fails
        echo "Pip OpenMP not found, trying Homebrew..."
        brew install libomp
        if [[ "$CIBW_BUILD" == *-macosx_arm64 ]]; then
            PREFIX="/opt/homebrew"
        else
            PREFIX="/usr/local"
        fi
    fi

    export CC=/usr/bin/clang
    export CXX=/usr/bin/clang++
    export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
    export CFLAGS="$CFLAGS -I$PREFIX/include"
    export CXXFLAGS="$CXXFLAGS -I$PREFIX/include"
    export LDFLAGS="$LDFLAGS -Wl,-rpath,$PREFIX/lib -L$PREFIX/lib -lomp"
    
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

pip3 install setuptools wheel twine
python setup.py clean build sdist bdist_wheel