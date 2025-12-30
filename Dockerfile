# =============================================================================
# Dockerfile para Servidor MCP SQL Server
# =============================================================================
# Build: docker build -t sqlserver-mcp .
# Run:   docker run -it --env-file .env sqlserver-mcp
# =============================================================================

FROM python:3.12-slim

# Metadados
LABEL maintainer="Moises Gomes"
LABEL description="Servidor MCP para Microsoft SQL Server"
LABEL version="1.0.0"

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalar dependências do sistema para ODBC
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    apt-transport-https \
    ca-certificates \
    unixodbc \
    unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Adicionar repositório Microsoft e instalar driver ODBC
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list | tee /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Criar diretório da aplicação
WORKDIR /app

# Copiar requirements primeiro (para cache de camadas)
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY server.py .
COPY client_smoke.py .

# Criar usuário não-root para segurança
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Porta padrão (não usada no modo stdio, mas útil para documentação)
EXPOSE 8000

# Healthcheck (opcional - verifica se o Python está funcionando)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import pyodbc; print('OK')" || exit 1

# Comando padrão - executa o servidor MCP
CMD ["python", "server.py"]

