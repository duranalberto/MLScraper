FROM python:3.14.5-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Los_Angeles

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    less \
    openssh-client \
    procps \
    tzdata \
    wget \
    zsh \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/ohmyzsh/ohmyzsh.git /root/.oh-my-zsh \
    && git clone --depth=1 https://github.com/romkatv/powerlevel10k.git /root/.oh-my-zsh/custom/themes/powerlevel10k \
    && git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions /root/.oh-my-zsh/custom/plugins/zsh-autosuggestions \
    && git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting.git /root/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting \
    && { \
    echo 'export ZSH="$HOME/.oh-my-zsh"'; \
    echo 'ZSH_THEME="powerlevel10k/powerlevel10k"'; \
    echo 'plugins=(git zsh-autosuggestions zsh-syntax-highlighting)'; \
    echo 'POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true'; \
    echo 'POWERLEVEL9K_INSTANT_PROMPT=quiet'; \
    echo 'POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir vcs)'; \
    echo 'POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()'; \
    echo 'POWERLEVEL9K_SHORTEN_STRATEGY="truncate_to_first_and_last"'; \
    echo 'POWERLEVEL9K_MODE="nerdfont-complete"'; \
    echo 'source $ZSH/oh-my-zsh.sh'; \
    echo '[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh'; \
    } > /root/.zshrc

WORKDIR /workspaces/MLScraper

COPY requirements.txt requirements-dev.txt ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt -r requirements-dev.txt \
    && python -m playwright install --with-deps chromium
