FROM python:3.12-slim

LABEL maintainer="MU Team"
# LABEL org.opencontainers.image.source="https://github.com/YOUR_ORG/mu"
LABEL org.opencontainers.image.description="MU Semantic Diff GitHub Action"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy the MU package source
COPY . /app/

# Install MU package
RUN pip install --no-cache-dir -e .

# Copy entrypoint script
COPY tools/action-mu/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Configure git for GitHub Actions
RUN git config --global --add safe.directory /github/workspace
RUN git config --global --add safe.directory '*'

ENTRYPOINT ["/entrypoint.sh"]
