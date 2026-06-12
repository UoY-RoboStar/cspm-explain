FROM node:20

ARG TZ
ENV TZ="$TZ"

ARG CLAUDE_CODE_VERSION=latest

# Install basic development tools and iptables/ipset
RUN apt-get update && apt-get install -y --no-install-recommends \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  locales \
  man-db \
  unzip \
  gnupg2 \
  gh \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  aggregate \
  jq \
  nano \
  vim \
  graphviz \
  curl \
  wget \
  strace \
  ca-certificates \
  build-essential \
  software-properties-common \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Generate and set the locale to prevent C++ runtime facet crashes
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8  
ENV LANGUAGE=en_US:en  
ENV LC_ALL=en_US.UTF-8

# Install Rust for the node user
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile default \
  && . /root/.cargo/env \
  && rustup component add rustfmt clippy \
  && cp -r /root/.cargo /home/node/.cargo \
  && cp -r /root/.rustup /home/node/.rustup \
  && chown -R node:node /home/node/.cargo /home/node/.rustup

# Ensure default node user has access to /usr/local/share
RUN mkdir -p /usr/local/share/npm-global && \
  chown -R node:node /usr/local/share

ARG USERNAME=node

# Persist bash history.
RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  && mkdir /commandhistory \
  && touch /commandhistory/.bash_history \
  && chown -R $USERNAME /commandhistory

# Set `DEVCONTAINER` environment variable to help with orientation
ENV DEVCONTAINER=true

# Create workspace and config directories and set permissions
RUN mkdir -p /workspace /home/node/.claude && \
  chown -R node:node /workspace /home/node/.claude

WORKDIR /workspace

ARG GIT_DELTA_VERSION=0.18.2
RUN ARCH=$(dpkg --print-architecture) && \
  wget "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  sudo dpkg -i "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  rm "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb"

# Set up non-root user
USER node

# Install global packages
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin:/home/node/.cargo/bin

# Set up Rust environment variables
ENV CARGO_HOME=/home/node/.cargo
ENV RUSTUP_HOME=/home/node/.rustup

# Set the default shell to zsh rather than sh
ENV SHELL=/bin/zsh

# Set the default editor and visual
ENV EDITOR=nano
ENV VISUAL=nano

# Default powerline10k theme
ARG ZSH_IN_DOCKER_VERSION=1.2.0
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v${ZSH_IN_DOCKER_VERSION}/zsh-in-docker.sh)" -- \
  -p git \
  -p fzf \
  -a "source /usr/share/doc/fzf/examples/key-bindings.zsh" \
  -a "source /usr/share/doc/fzf/examples/completion.zsh" \
  -a "export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  -x

# Install Claude
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}


# Copy and set up firewall script
COPY init-firewall.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh && \
  echo "node ALL=(root) NOPASSWD: ALL" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall

# Install FDR4 and handle legacy dependencies (libpng12-0 and libtinfo.so.5) safely
RUN ARCH=$(dpkg --print-architecture) && \
    # 1. Install equivs FIRST while apt is completely healthy
    apt-get update && apt-get install -y --no-install-recommends equivs && \
    \
    # 2. Build and install the dummy libpng12-0 package immediately to satisfy apt metadata
    mkdir /tmp/equivs && cd /tmp/equivs && \
    echo "Section: misc" > libpng12-dummy && \
    echo "Priority: optional" >> libpng12-dummy && \
    echo "Package: libpng12-0" >> libpng12-dummy && \
    echo "Version: 1.2.54-999" >> libpng12-dummy && \
    echo "Description: Fake libpng12 package to satisfy FDR dependency requirements" >> libpng12-dummy && \
    equivs-control libpng12-0 && \
    equivs-build libpng12-dummy && \
    dpkg -i libpng12-0_*.deb && \
    rm -rf /tmp/equivs && \
    \
    # 3. Extract the ACTUAL physical libpng12 binaries to /usr/local/lib
    mkdir /tmp/libpng && cd /tmp/libpng && \
    wget -q "http://archive.ubuntu.com/ubuntu/pool/main/libp/libpng/libpng12-0_1.2.54-1ubuntu1_amd64.deb" && \
    dpkg-deb -x *.deb . && \
    cp lib/*-linux-gnu/libpng12.so.0* /usr/local/lib/ && \
    rm -rf /tmp/libpng && \
    \
    # 4. Extract libtinfo5 binaries natively available in this image layer environment
    cd /tmp && \
    apt-get download libtinfo5 && \
    dpkg-deb -x libtinfo5_*.deb /tmp/libtinfo && \
    cp /tmp/libtinfo/lib/*-linux-gnu/libtinfo.so.5* /usr/local/lib/ && \
    rm -rf /tmp/libtinfo *.deb && \
    ldconfig && \
    \
    # 5. Configure Cocotec apt repository
    wget -qO - http://dl.cocotec.io/fdr/linux_deploy.key | gpg --dearmor -o /usr/share/keyrings/cocotec-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cocotec-archive-keyring.gpg] http://dl.cocotec.io/fdr/debian/ fdr release" > /etc/apt/sources.list.d/fdr.list && \
    \
    # 6. Now install FDR naturally (it will install cleanly because the dummy package is present!)
    apt-get update && \
    mkdir /tmp/fdr-download && cd /tmp/fdr-download && \
    apt-get download fdr && \
    dpkg -i fdr_*.deb && \
    cd / && \
    rm -rf /tmp/fdr-download && \
    \
    # 7. Purge equivs and clean up
    apt-get purge -y --auto-remove equivs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Fix place where FDR looks for certificates
RUN mkdir -p /etc/pki/tls/certs/ && ln -s /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt

# Install Python pip and the Anthropic SDK (system-wide so both root and node can use them)
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3 - --break-system-packages && \
    pip3 install --break-system-packages anthropic

USER node