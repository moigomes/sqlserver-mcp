## Servidor MCP: SQL Server (Não Oficial) desenvolvido em Python por Moises Gomes

Servidor MCP (Model Context Protocol) em Python para consultar Microsoft SQL Server via `pyodbc`, expondo ferramentas para teste de conexão, listar schemas/tabelas, descrever colunas e executar consultas de leitura.

### Pré-requisitos
- Python 3.10+
- Driver ODBC do SQL Server instalado
  - macOS:
    - Requer Homebrew e unixODBC
    - Aceite a licença da Microsoft quando solicitado
    - Comandos sugeridos:
      ```bash
      brew update
      brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
      brew install --no-sandbox msodbcsql18 mssql-tools18
      brew install unixodbc
      ```
- Acesso ao servidor SQL Server

### Instalação
1. Clone/abra este diretório `sqlserver-mcp/` na sua IDE
2. Crie o `.env` a partir do modelo:
   ```bash
   cp .env.example .env
   ```
   Ajuste `SQLSERVER_SERVER`, `SQLSERVER_DATABASE`, `SQLSERVER_USERNAME`, `SQLSERVER_PASSWORD` e demais flags conforme seu ambiente.
3. Crie um ambiente virtual e instale dependências:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

### Execução (modo MCP stdio)
O servidor fala MCP via STDIO. Normalmente você não executa manualmente; a Cursor invoca o processo. Para teste isolado, você pode apenas validar variáveis e dependências executando o arquivo (o processo ficará aguardando IO):
```bash
python server.py
```
Use Ctrl+C para encerrar.

### Integração com Cursor (mcpServers)
Abra as configurações da Cursor e adicione uma entrada em `mcpServers` similar a:
```json
{
  "mcpServers": {
    "sqlserver-mcp": {
      "command": "python", # ou o caminho do seu ambiente virtual
      "args": ["/sqlserver-mcp/server.py"], # ou o caminho do seu arquivo server.py
      "cwd": "/sqlserver-mcp", # ou o caminho do seu diretório
      "env": {
        "PYTHONPATH": ".",
        "PYTHONUNBUFFERED": "1",
        "FASTMCP_DEBUG": "true",
        "FASTMCP_LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```
Se você preferir usar um `.env`, mantenha-o no mesmo diretório do `server.py` (o `python-dotenv` fará o carregamento automático via `load_dotenv()`).

### Ferramentas expostas
- `test_connection()`: valida conexão e retorna `@@VERSION` e `DB_NAME()`
- `list_schemas()`: lista schemas do banco atual
- `list_tables(schema?)`: lista tabelas (opcionalmente filtrando por schema)
- `describe_table(table_name, schema?)`: descreve colunas de uma tabela
- `run_query(sql, max_rows=1000)`: executa somente SELECT/CTE, limitado por `max_rows`

### Dicas
- Em macOS, prefira `SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server`
- Se o servidor exigir TLS com certificado autoassinado, você pode definir `SQLSERVER_TRUST_SERVER_CERTIFICATE=yes` (apenas para ambientes de desenvolvimento)
- Para conexões por porta não padrão, defina `SQLSERVER_PORT=1433`

### Segurança
- `run_query` bloqueia comandos não-SELECT (apenas SELECT/CTE). Em produção, avalie colocar uma camada de whitelisting por schema/tabela ou uma view segura para consultas.
