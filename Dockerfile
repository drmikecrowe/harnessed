# Code Container
# Generic Dockerfile for running coding tools in isolated project environments

FROM ubuntu:24.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set timezone to America/New_York (EST)
ENV TZ=America/New_York
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install system dependencies and common build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    unzip \
    ca-certificates \
    libssl-dev \
    zlib1g-dev \
    libffi-dev \
    vim \
    tree \
    gnupg \
    iptables

# Install 1Password CLI and desktop app (for SSH signing with op-ssh-sign)
RUN curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
    tee /etc/apt/sources.list.d/1password.list && \
    apt-get update && apt-get install -y 1password 1password-cli && \
    rm -rf /var/lib/apt/lists/*

# Accept build-time username (defaults to ubuntu)
ARG USERNAME=ubuntu

# Rename ubuntu user and move home to /container/$USERNAME
RUN mkdir -p /container && \
    usermod -l ${USERNAME} ubuntu && \
    groupmod -n ${USERNAME} ubuntu && \
    usermod -d /container/${USERNAME} -m ${USERNAME}

USER ${USERNAME}
WORKDIR /container/${USERNAME}

# Install mise (modern runtime manager)
RUN curl -fsSL https://mise.run | bash
ENV PATH="/container/${USERNAME}/.local/share/mise/shims:/container/${USERNAME}/.local/bin:${PATH}"

# Managed pnpm supply-chain config (Phase 3 / BLD-01). Must be in place before
# mise's npm: backend resolves globals (RESEARCH Pitfall 5). The legacy home is
# /container/${USERNAME}; COPY to a temp path then mv (COPY dest paths don't
# expand ARG the same way RUN does).
USER root
COPY lib/pnpm/config.yaml /tmp/pnpm-config.yaml
RUN mkdir -p /container/${USERNAME}/.config/pnpm && \
    mv /tmp/pnpm-config.yaml /container/${USERNAME}/.config/pnpm/config.yaml && \
    chown -R ${USERNAME}:${USERNAME} /container/${USERNAME}/.config/pnpm
USER ${USERNAME}

# Configure mise tools. npm.package_manager=pnpm routes the npm: tools through pnpm
# so the managed policy governs them (RESEARCH Pitfall 5); set BEFORE `mise use -g`.
# pnpm@11 (not @latest) so the v11 supply-chain defaults are in effect (Node 22+ required).
RUN mise settings set experimental true && \
    mise settings set npm.package_manager pnpm && \
    mise use -g \
        node@22 \
        pnpm@11 \
        python@latest \
        fd \
        ripgrep \
        npm:opencode-ai \
        npm:@openai/codex \
        npm:@google/gemini-cli && \
    mise install && \
    mise trust ~/.config/mise/config.toml

# Install extra user-specified tools (edit extra-tools.txt to add more)
# Switch to root for COPY to avoid Podman overlay layer corrupting home dir ownership
USER root
COPY extra-tools.txt /tmp/extra-tools.txt
RUN chown -R ${USERNAME}:${USERNAME} /container/${USERNAME}
USER ${USERNAME}
RUN grep -v '^\s*#' /tmp/extra-tools.txt | grep -v '^\s*$' | awk '{print $1}' | \
    xargs -r mise use -g && mise install

# Install Claude Code globally via official installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Configure bash prompt to show container name
RUN echo 'PS1="\[\033[01;32m\][code-container]\[\033[00m\] \[\033[01;34m\]\w\[\033[00m\]\$ "' >> /container/${USERNAME}/.bashrc

# Source mise in bashrc for interactive shells
RUN echo 'eval "$(mise activate bash)"' >> /container/${USERNAME}/.bashrc && \
    echo 'mise trust -a 2>/dev/null' >> /container/${USERNAME}/.bashrc && \
    echo 'mise up 2>/dev/null' >> /container/${USERNAME}/.bashrc

# Default command: bash shell
CMD ["/bin/bash"]
