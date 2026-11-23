FROM python:3.12-slim

# Instalação de dependências
RUN apt-get update && apt-get install -y \
    git \
    pkg-config \
    build-essential \
    default-libmysqlclient-dev \
    # Dependências do WeasyPrint
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
    # Conversão de áudio/vídeo do CRM de WhatsApp
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Usuário sem privilégio (UID/GID fixos para o chown das pastas montadas no
# servidor: mediafiles/, mediafiles_privado/, logs/, staticfiles/).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --no-create-home --shell /usr/sbin/nologin app

# Define o diretório de trabalho
WORKDIR /app

# Copia o arquivo de requisitos e instala as dependências
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY --chown=app:app . .
RUN mkdir -p mediafiles mediafiles_privado logs staticfiles \
    && chown app:app mediafiles mediafiles_privado logs staticfiles

USER app

# Porta do gunicorn (gunicorn.conf.py, PORT padrão 8010)
EXPOSE 8010
