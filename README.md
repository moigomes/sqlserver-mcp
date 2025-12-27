# 🗄️ Servidor MCP: SQL Server (Não Oficial)

**Desenvolvido em Python por Moises Gomes**

Servidor MCP (Model Context Protocol) em Python para consultar Microsoft SQL Server via `pyodbc`, expondo ferramentas para exploração de banco de dados, execução de consultas seguras e análise de estrutura.

---

## 📋 Índice

- [Pré-requisitos](#-pré-requisitos)
- [Instalação](#-instalação)
  - [macOS](#macos)
  - [Linux (Ubuntu/Debian)](#linux-ubuntudebian)
  - [Windows](#windows)
- [Configuração](#-configuração)
- [Execução](#-execução)
- [Integração com Cursor](#-integração-com-cursor)
- [Ferramentas Disponíveis](#-ferramentas-disponíveis)
- [Variáveis de Ambiente](#-variáveis-de-ambiente)
- [Segurança](#-segurança)
- [Dicas](#-dicas)
- [Outros Clientes Compatíveis](#-outros-clientes-compatíveis)

---

## 📦 Pré-requisitos

- **Python 3.10+**
- **Driver ODBC do SQL Server** instalado
- Acesso a um servidor SQL Server

---

## 🚀 Instalação

### macOS

1. **Instale o Homebrew** (se ainda não tiver):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Instale o driver ODBC e ferramentas**:
   ```bash
   brew update
   brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
   brew install --no-sandbox msodbcsql18 mssql-tools18
   brew install unixodbc
   ```
   > ⚠️ Aceite a licença da Microsoft quando solicitado.

3. **Clone o repositório e configure**:
   ```bash
   git clone <url-do-repositorio>
   cd sqlserver-mcp
   
   # Crie o ambiente virtual
   python3 -m venv .venv
   source .venv/bin/activate
   
   # Instale as dependências
   pip install -r requirements.txt
   
   # Configure as variáveis de ambiente
   cp .env.example .env
   # Edite o arquivo .env com suas credenciais
   ```

---

### Linux (Ubuntu/Debian)

1. **Adicione o repositório da Microsoft**:
   ```bash
   curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
   curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
   ```

2. **Instale o driver ODBC**:
   ```bash
   sudo apt-get update
   sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
   sudo ACCEPT_EULA=Y apt-get install -y mssql-tools18
   sudo apt-get install -y unixodbc-dev
   ```

3. **Adicione as ferramentas ao PATH** (opcional):
   ```bash
   echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> ~/.bashrc
   source ~/.bashrc
   ```

4. **Clone o repositório e configure**:
   ```bash
   git clone <url-do-repositorio>
   cd sqlserver-mcp
   
   # Crie o ambiente virtual
   python3 -m venv .venv
   source .venv/bin/activate
   
   # Instale as dependências
   pip install -r requirements.txt
   
   # Configure as variáveis de ambiente
   cp .env.example .env
   nano .env  # ou use seu editor preferido
   ```

---

### Windows

1. **Baixe e instale o driver ODBC**:
   - Acesse: https://learn.microsoft.com/pt-br/sql/connect/odbc/download-odbc-driver-for-sql-server
   - Baixe o "ODBC Driver 18 for SQL Server"
   - Execute o instalador e siga as instruções

2. **Instale o Python** (se ainda não tiver):
   - Baixe em: https://www.python.org/downloads/
   - Durante a instalação, marque "Add Python to PATH"

3. **Clone o repositório e configure**:
   ```powershell
   git clone <url-do-repositorio>
   cd sqlserver-mcp
   
   # Crie o ambiente virtual
   python -m venv .venv
   .venv\Scripts\activate
   
   # Instale as dependências
   pip install -r requirements.txt
   
   # Configure as variáveis de ambiente
   copy .env.example .env
   notepad .env
   ```

---

## ⚙️ Configuração

### Arquivo `.env`

Crie um arquivo `.env` na raiz do projeto com as seguintes variáveis:

```env
# Conexão obrigatória
SQLSERVER_SERVER=seu_servidor
SQLSERVER_DATABASE=seu_banco
SQLSERVER_USERNAME=seu_usuario
SQLSERVER_PASSWORD=sua_senha

# Opcionais
SQLSERVER_PORT=1433
SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server
SQLSERVER_ENCRYPT=yes
SQLSERVER_TRUST_SERVER_CERTIFICATE=no
SQLSERVER_TRUSTED_CONNECTION=no

# Logging (DEBUG, INFO, WARNING, ERROR)
SQLSERVER_LOG_LEVEL=INFO

# Connection Pool
SQLSERVER_POOL_SIZE=5
SQLSERVER_POOL_IDLE_TIME=300
```

### Autenticação Windows (Trusted Connection)

Para usar autenticação integrada do Windows:

```env
SQLSERVER_SERVER=seu_servidor
SQLSERVER_DATABASE=seu_banco
SQLSERVER_TRUSTED_CONNECTION=yes
```

---

## ▶️ Execução

### Modo Standalone (para testes)

```bash
# macOS/Linux
source .venv/bin/activate
python server.py

# Windows
.venv\Scripts\activate
python server.py
```

O servidor ficará aguardando conexões via STDIO. Use `Ctrl+C` para encerrar.

### Teste de Conexão

Execute o cliente de teste para validar a configuração:

```bash
python client_smoke.py
```

---

## 🔌 Integração com Cursor

Abra as configurações do Cursor (`Cmd+Shift+J` ou `Ctrl+Shift+J`) e adicione em `mcpServers`:

### macOS/Linux

```json
{
  "mcpServers": {
    "sqlserver-mcp": {
      "command": "/caminho/para/sqlserver-mcp/.venv/bin/python",
      "args": ["/caminho/para/sqlserver-mcp/server.py"],
      "cwd": "/caminho/para/sqlserver-mcp",
      "env": {
        "PYTHONPATH": ".",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

### Windows

```json
{
  "mcpServers": {
    "sqlserver-mcp": {
      "command": "C:\\caminho\\para\\sqlserver-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\caminho\\para\\sqlserver-mcp\\server.py"],
      "cwd": "C:\\caminho\\para\\sqlserver-mcp",
      "env": {
        "PYTHONPATH": ".",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

> 💡 **Dica**: As variáveis de ambiente podem ser definidas no arquivo `.env` (carregadas automaticamente) ou diretamente na configuração do Cursor.

---

## 🛠️ Ferramentas Disponíveis

### Conexão e Diagnóstico

| Ferramenta | Descrição | Parâmetros |
|------------|-----------|------------|
| `test_connection()` | Valida conexão e retorna versão do SQL Server | - |
| `pool_stats()` | Retorna estatísticas do pool de conexões | - |

### Exploração de Schema

| Ferramenta | Descrição | Parâmetros |
|------------|-----------|------------|
| `list_schemas()` | Lista schemas disponíveis | - |
| `list_tables(schema?)` | Lista tabelas do banco | `schema` (opcional) |
| `list_views(schema?)` | Lista views do banco | `schema` (opcional) |
| `list_procedures(schema?)` | Lista stored procedures | `schema` (opcional) |
| `list_functions(schema?)` | Lista funções do usuário | `schema` (opcional) |

### Análise de Tabelas

| Ferramenta | Descrição | Parâmetros |
|------------|-----------|------------|
| `describe_table(table_name, schema?)` | Descreve colunas de uma tabela | `table_name`, `schema` |
| `get_indexes(table_name, schema?)` | Retorna índices da tabela | `table_name`, `schema` |
| `get_primary_key(table_name, schema?)` | Retorna chave primária | `table_name`, `schema` |
| `get_foreign_keys(table_name, schema?)` | Retorna chaves estrangeiras | `table_name`, `schema` |
| `get_table_relationships(table_name, schema?)` | Retorna todos os relacionamentos | `table_name`, `schema` |
| `get_table_row_count(table_name, schema?)` | Contagem aproximada de linhas | `table_name`, `schema` |

### Execução de Consultas

| Ferramenta | Descrição | Parâmetros |
|------------|-----------|------------|
| `run_query(sql, max_rows?)` | Executa consulta SELECT/CTE | `sql`, `max_rows` (padrão: 1000) |

---

## 🔐 Variáveis de Ambiente

| Variável | Obrigatório | Padrão | Descrição |
|----------|-------------|--------|-----------|
| `SQLSERVER_SERVER` | ✅ Sim | - | Endereço do servidor |
| `SQLSERVER_DATABASE` | Não | - | Nome do banco de dados |
| `SQLSERVER_USERNAME` | Condicional* | - | Usuário para autenticação |
| `SQLSERVER_PASSWORD` | Condicional* | - | Senha para autenticação |
| `SQLSERVER_PORT` | Não | 1433 | Porta do servidor |
| `SQLSERVER_DRIVER` | Não | ODBC Driver 18 for SQL Server | Driver ODBC |
| `SQLSERVER_ENCRYPT` | Não | yes | Criptografar conexão |
| `SQLSERVER_TRUST_SERVER_CERTIFICATE` | Não | no | Confiar em certificado autoassinado |
| `SQLSERVER_TRUSTED_CONNECTION` | Não | no | Usar autenticação Windows |
| `SQLSERVER_LOG_LEVEL` | Não | INFO | Nível de log (DEBUG/INFO/WARNING/ERROR) |
| `SQLSERVER_POOL_SIZE` | Não | 5 | Tamanho máximo do pool de conexões |
| `SQLSERVER_POOL_IDLE_TIME` | Não | 300 | Tempo máximo de ociosidade (segundos) |

> \* `SQLSERVER_USERNAME` e `SQLSERVER_PASSWORD` são obrigatórios se `SQLSERVER_TRUSTED_CONNECTION` não estiver como `yes`.

---

## 🔒 Segurança

O servidor implementa múltiplas camadas de segurança:

### 1. Validação de Queries
- ✅ Apenas `SELECT` e `WITH` (CTEs) são permitidos
- ❌ Bloqueia: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`
- ❌ Bloqueia: `EXEC`, `EXECUTE`, `xp_*`, `sp_configure`
- ❌ Bloqueia: `OPENROWSET`, `OPENDATASOURCE`, `BULK`

### 2. Proteção contra SQL Injection
- ❌ Múltiplos statements são bloqueados (ex: `SELECT 1; DROP TABLE x`)
- ✅ Queries parametrizadas são usadas internamente

### 3. Transação Read-Only
- Todas as queries são executadas em transação com `ROLLBACK` automático
- Mesmo que algo passe pelas validações, nada será persistido

### Códigos de Erro

| Código | Categoria | Descrição |
|--------|-----------|-----------|
| E101 | Conexão | Falha na conexão |
| E102 | Conexão | Timeout |
| E201 | Configuração | Configuração ausente |
| E301 | Validação | Erro de validação de entrada |
| E303 | Segurança | Query bloqueada por segurança |
| E401 | Execução | Erro na query |
| E402 | Execução | Tabela não encontrada |
| E404 | Execução | Permissão negada |

---

## 💡 Dicas

### Driver ODBC
- **macOS**: Use `SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server`
- **Linux**: Use `SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server`
- **Windows**: Use `SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server`

### Certificado Autoassinado
Para ambientes de desenvolvimento com certificado autoassinado:
```env
SQLSERVER_TRUST_SERVER_CERTIFICATE=yes
```
> ⚠️ **Não use em produção!**

### Porta Não Padrão
```env
SQLSERVER_PORT=1434
```

### Debug
Para logs detalhados:
```env
SQLSERVER_LOG_LEVEL=DEBUG
```

### Pool de Conexões
Para ajustar o pool conforme sua carga:
```env
SQLSERVER_POOL_SIZE=10
SQLSERVER_POOL_IDLE_TIME=600
```

---

## 🔌 Outros Clientes Compatíveis

Este servidor MCP pode ser usado em qualquer cliente compatível com o **Model Context Protocol**. A configuração é similar à do Cursor.

### IDEs e Editores
- **Claude Desktop** (macOS, Windows) - App oficial da Anthropic
- **VS Code + GitHub Copilot** - Suporte MCP em preview
- **Zed** (macOS, Linux) - Editor moderno
- **Windsurf** - IDE focada em IA
- **Continue** - Extensão open-source para VS Code

### Mobile e Desktop
- **5ire** - Assistente IA desktop
- **AIaW** - Cliente de chat multiplataforma
- **Jenova AI** - Mobile + Desktop
- **Systemprompt MCP** (iOS) - Controle por voz

### Cloud e Enterprise
- **Amazon Q Developer** - CLI da AWS
- **Microsoft Sentinel** - Segurança com MCP

> 📖 Lista completa de clientes: https://glama.ai/mcp/clients  
> 📖 Especificação MCP: https://modelcontextprotocol.io

---

## 📄 Licença

Este projeto é não oficial e desenvolvido de forma independente.

---

## 🤝 Contribuições

Contribuições são bem-vindas! Abra uma issue ou pull request.
