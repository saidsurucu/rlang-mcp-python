#!/bin/bash

# Build R Server MCP Docker Image
# Multi-platform support for x86_64 and ARM64

set -e

IMAGE_NAME="r-server-mcp"
TAG="latest"
FULL_NAME="${IMAGE_NAME}:${TAG}"

echo "🐳 Building R Server MCP Docker image..."
echo "📦 Image: ${FULL_NAME}"

# Build for current platform
docker build \
    -f Dockerfile.r-server \
    -t "${FULL_NAME}" \
    .

echo "✅ Build completed successfully!"
echo "🚀 Image ready: ${FULL_NAME}"

# Test the image
echo "🧪 Testing image..."
docker run --rm "${FULL_NAME}" Rscript -e "cat('R version:', R.version.string, '\n'); library(readxl); library(ggplot2); cat('✅ All packages loaded successfully!\n')"

echo "🎉 Image is ready for use!"
echo ""
echo "To use in your MCP server:"
echo "  docker run -d --name r-container ${FULL_NAME}"