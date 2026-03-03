#!/bin/bash
# Build dEQP-GLES2 NRO with embedded romfs caselist.
#
# Usage:
#   ./build_nro.sh                  # Build with current.txt caselist
#   ./build_nro.sh pass             # Build with pass.txt (regression mode)
#   ./build_nro.sh skip-caselist    # Build NRO without regenerating caselist
#
# Prerequisites:
#   - CTS already compiled (make -j4 in build-switch/)
#   - Python 3 available

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(cd "$SCRIPT_DIR/../../../build-switch/modules/gles2" && pwd)"
ROMFS_DIR="$SCRIPT_DIR/romfs"

MODE="${1:-current}"

# Step 1: Generate caselist (unless skip-caselist)
if [ "$MODE" != "skip-caselist" ]; then
    echo "=== Generating caselist from $MODE.txt ==="
    python3 "$SCRIPT_DIR/manage_tests.py" generate-caselist "$MODE"
else
    echo "=== Skipping caselist generation ==="
fi

# Verify caselist exists
if [ ! -f "$ROMFS_DIR/caselist.txt" ]; then
    echo "WARNING: No romfs/caselist.txt found. NRO will use fallback caselist."
fi

# Step 2: Strip ELF
echo "=== Stripping ELF ==="
aarch64-none-elf-strip -o "$BUILD_DIR/deqp-gles2-stripped.elf" "$BUILD_DIR/deqp-gles2.elf"

# Step 3: Create NACP
echo "=== Creating NACP ==="
nacptool --create "dEQP-GLES2" "SwitchGLES" "1.0" "$BUILD_DIR/deqp-gles2.nacp"

# Step 4: Build NRO with romfs
echo "=== Building NRO with romfs ==="
elf2nro "$BUILD_DIR/deqp-gles2-stripped.elf" "$BUILD_DIR/deqp-gles2.nro" \
    --nacp="$BUILD_DIR/deqp-gles2.nacp" \
    --romfsdir="$ROMFS_DIR"

NRO_SIZE=$(stat -c%s "$BUILD_DIR/deqp-gles2.nro" 2>/dev/null || stat -f%z "$BUILD_DIR/deqp-gles2.nro" 2>/dev/null || echo "unknown")
echo "=== Done: $BUILD_DIR/deqp-gles2.nro ($NRO_SIZE bytes) ==="
echo ""
echo "Deploy with:"
echo "  nxlink -a 192.168.1.103 -s $BUILD_DIR/deqp-gles2.nro"
