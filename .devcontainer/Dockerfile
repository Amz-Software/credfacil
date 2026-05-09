FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    curl \
    zsh \
    git \
    python3 \
    python3-pip \
    tzdata \
    pkg-config \
    libmysqlclient-dev \
    gcc \
    g++ \
    python3-dev \
    libffi-dev \
    libssl-dev \
    redis-server \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgobject-2.0-0 \
    libcairo2 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fontconfig \
    libpixman-1-0 \
    libxcb-render0 \
    libxcb-shm0 \
    libxrender1 \
    libdatrie1 \
    libfribidi0 \
    libharfbuzz0b \
    libthai0 \
    libgraphite2-3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" --unattended
RUN chsh -s $(which zsh)

RUN ln -fs /usr/share/zoneinfo/America/Belem /etc/localtime
RUN echo "America/Belem" > /etc/timezone

WORKDIR /app

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

SHELL ["/bin/zsh", "-c"]

COPY . .

EXPOSE 8000
