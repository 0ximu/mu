#!/bin/bash
# Update Homebrew formula with SHA256 hashes from GitHub release
# Usage: ./update-formula.sh v0.1.0

set -e

VERSION="${1:-v0.1.0}"
VERSION_NUM="${VERSION#v}"
FORMULA="mu.rb"
REPO="0ximu/mu"

echo "Updating formula for version $VERSION..."

# Download and compute SHA256 for each platform
declare -A URLS=(
    ["MACOS_ARM64"]="mu-macos-arm64"
    ["MACOS_X86_64"]="mu-macos-x86_64"
    ["LINUX_ARM64"]="mu-linux-arm64"
    ["LINUX_X86_64"]="mu-linux-x86_64"
)

for PLATFORM in "${!URLS[@]}"; do
    BINARY="${URLS[$PLATFORM]}"
    URL="https://github.com/$REPO/releases/download/$VERSION/$BINARY"

    echo "Fetching $BINARY..."
    if SHA=$(curl -sL "$URL" | shasum -a 256 | cut -d' ' -f1); then
        echo "  SHA256: $SHA"
        sed -i '' "s/PLACEHOLDER_SHA256_$PLATFORM/$SHA/g" "$FORMULA"
    else
        echo "  WARNING: Failed to fetch $BINARY"
    fi
done

# Update version
sed -i '' "s/version \".*\"/version \"$VERSION_NUM\"/g" "$FORMULA"

echo "Done! Updated $FORMULA for version $VERSION_NUM"
echo ""
echo "Next steps:"
echo "1. Create homebrew-tap repo: https://github.com/new"
echo "2. Copy mu.rb to homebrew-tap/Formula/mu.rb"
echo "3. Users install with: brew tap 0ximu/tap && brew install mu"
