import atexit
import functools
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional, TypeVar

import pyodbc
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


load_dotenv()

# ============================================================================
# EXCEÇÕES CUSTOMIZADAS
# ============================================================================
class ErrorCode(Enum):
    """Códigos de erro padronizados."""
    # Erros de conexão (1xx)
    CONNECTION_FAILED = "E101"
    CONNECTION_TIMEOUT = "E102"
    CONNECTION_POOL_EXHAUSTED = "E103"
    
    # Erros de configuração (2xx)
    MISSING_CONFIG = "E201"
    INVALID_CONFIG = "E202"
    
    # Erros de validação (3xx)
    VALIDATION_ERROR = "E301"
    INVALID_QUERY = "E302"
    SECURITY_VIOLATION = "E303"
    
    # Erros de execução (4xx)
    QUERY_ERROR = "E401"
    TABLE_NOT_FOUND = "E402"
    COLUMN_NOT_FOUND = "E403"
    PERMISSION_DENIED = "E404"
    
    # Erros internos (5xx)
    INTERNAL_ERROR = "E501"
    UNKNOWN_ERROR = "E599"


class SQLServerMCPError(Exception):
    """Exceção base para todos os erros do servidor MCP SQL Server."""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.original_error = original_error
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte o erro para um dicionário estruturado."""
        result = {
            "error": True,
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result
    
    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


class ConnectionError(SQLServerMCPError):
    """Erro de conexão com o banco de dados."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCode.CONNECTION_FAILED, **kwargs)


class ConfigurationError(SQLServerMCPError):
    """Erro de configuração."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCode.MISSING_CONFIG, **kwargs)


class ValidationError(SQLServerMCPError):
    """Erro de validação de entrada."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCode.VALIDATION_ERROR, **kwargs)


class SecurityError(SQLServerMCPError):
    """Erro de segurança (query bloqueada)."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCode.SECURITY_VIOLATION, **kwargs)


class QueryError(SQLServerMCPError):
    """Erro na execução de query."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCode.QUERY_ERROR, **kwargs)


# Mapeamento de códigos de erro do SQL Server para mensagens amigáveis
SQL_ERROR_MESSAGES: Dict[str, tuple[ErrorCode, str]] = {
    # Erros de conexão
    "08001": (ErrorCode.CONNECTION_FAILED, "Não foi possível conectar ao servidor SQL Server"),
    "08S01": (ErrorCode.CONNECTION_FAILED, "Conexão perdida com o servidor"),
    "HYT00": (ErrorCode.CONNECTION_TIMEOUT, "Timeout na conexão com o servidor"),
    "HYT01": (ErrorCode.CONNECTION_TIMEOUT, "Timeout na conexão expirado"),
    
    # Erros de autenticação
    "28000": (ErrorCode.CONNECTION_FAILED, "Falha na autenticação. Verifique usuário e senha"),
    "18456": (ErrorCode.CONNECTION_FAILED, "Login falhou. Usuário ou senha incorretos"),
    
    # Erros de permissão
    "42000": (ErrorCode.PERMISSION_DENIED, "Permissão negada para executar esta operação"),
    
    # Erros de objeto não encontrado
    "42S02": (ErrorCode.TABLE_NOT_FOUND, "Tabela ou view não encontrada"),
    "42S22": (ErrorCode.COLUMN_NOT_FOUND, "Coluna não encontrada"),
    
    # Erros de sintaxe
    "42S01": (ErrorCode.QUERY_ERROR, "Objeto já existe no banco de dados"),
    "37000": (ErrorCode.QUERY_ERROR, "Erro de sintaxe na query SQL"),
}


def _parse_pyodbc_error(error: pyodbc.Error) -> tuple[ErrorCode, str, Dict[str, Any]]:
    """Extrai informações estruturadas de um erro pyodbc."""
    error_args = error.args
    
    if len(error_args) >= 2:
        sqlstate = error_args[0]
        message = error_args[1]
    else:
        sqlstate = "UNKNOWN"
        message = str(error)
    
    # Tenta extrair o código de erro do SQL Server da mensagem
    sql_error_code = None
    if "[SQL Server]" in message:
        # Formato típico: [SQL Server]Mensagem (código)
        import re as regex
        match = regex.search(r"\((\d+)\)", message)
        if match:
            sql_error_code = match.group(1)
    
    # Busca mensagem amigável no mapeamento
    if sqlstate in SQL_ERROR_MESSAGES:
        code, friendly_message = SQL_ERROR_MESSAGES[sqlstate]
    elif sql_error_code and sql_error_code in SQL_ERROR_MESSAGES:
        code, friendly_message = SQL_ERROR_MESSAGES[sql_error_code]
    else:
        code = ErrorCode.QUERY_ERROR
        friendly_message = "Erro ao executar operação no banco de dados"
    
    details = {
        "sqlstate": sqlstate,
        "original_message": message,
    }
    if sql_error_code:
        details["sql_error_code"] = sql_error_code
    
    return code, friendly_message, details


# Type variable para o decorator
F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator para tratamento padronizado de erros nas ferramentas MCP."""
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        
        except SQLServerMCPError:
            # Já é um erro customizado, apenas re-lança
            raise
        
        except pyodbc.Error as e:
            # Converte erro pyodbc para erro customizado
            code, message, details = _parse_pyodbc_error(e)
            logger.error(f"Erro pyodbc em {func.__name__}: {e}")
            raise SQLServerMCPError(
                message=message,
                code=code,
                details=details,
                original_error=e,
            )
        
        except ValueError as e:
            # Erros de validação
            logger.warning(f"Erro de validação em {func.__name__}: {e}")
            raise ValidationError(
                message=str(e),
                original_error=e,
            )
        
        except Exception as e:
            # Erro inesperado
            logger.exception(f"Erro inesperado em {func.__name__}: {e}")
            raise SQLServerMCPError(
                message=f"Erro interno: {str(e)}",
                code=ErrorCode.INTERNAL_ERROR,
                original_error=e,
            )
    
    return wrapper  # type: ignore


# ============================================================================
# CONFIGURAÇÃO DE LOGGING
# ============================================================================
# Nível de log controlado por variável de ambiente (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = os.getenv("SQLSERVER_LOG_LEVEL", "INFO").upper()

# Formato estruturado para logs
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
)

logger = logging.getLogger("sqlserver-mcp")

app = FastMCP("sqlserver-mcp")

logger.info("Servidor MCP SQL Server inicializado")


def _build_connection_string() -> str:
    """Monta a connection string do SQL Server a partir de variáveis de ambiente.

    Variáveis suportadas:
      - SQLSERVER_DRIVER (padrão: "ODBC Driver 18 for SQL Server")
      - SQLSERVER_SERVER (obrigatório)
      - SQLSERVER_PORT (opcional)
      - SQLSERVER_DATABASE (opcional)
      - SQLSERVER_USERNAME (opcional se Trusted_Connection=yes)
      - SQLSERVER_PASSWORD (opcional se Trusted_Connection=yes)
      - SQLSERVER_TRUSTED_CONNECTION (yes/no; padrão: no)
      - SQLSERVER_ENCRYPT (yes/no; padrão: yes)
      - SQLSERVER_TRUST_SERVER_CERTIFICATE (yes/no; padrão: no)
    """
    driver = os.getenv("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server")
    server = os.getenv("SQLSERVER_SERVER")
    if not server:
        raise ConfigurationError(
            "A variável de ambiente SQLSERVER_SERVER é obrigatória",
            details={"missing_var": "SQLSERVER_SERVER"},
        )

    port = os.getenv("SQLSERVER_PORT")
    server_part = f"{server},{port}" if port else server

    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")

    trusted_connection = os.getenv("SQLSERVER_TRUSTED_CONNECTION", "no").lower()
    encrypt = os.getenv("SQLSERVER_ENCRYPT", "yes").lower()
    trust_cert = os.getenv("SQLSERVER_TRUST_SERVER_CERTIFICATE", "no").lower()

    parts: List[str] = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server_part}",
        f"Encrypt={'yes' if encrypt in ('1','true','yes') else 'no'}",
        f"TrustServerCertificate={'yes' if trust_cert in ('1','true','yes') else 'no'}",
    ]

    if database:
        parts.append(f"DATABASE={database}")

    if trusted_connection in ("1", "true", "yes"):
        parts.append("Trusted_Connection=yes")
    else:
        if not username or not password:
            raise ConfigurationError(
                "Credenciais não configuradas. Defina SQLSERVER_USERNAME e SQLSERVER_PASSWORD "
                "ou habilite SQLSERVER_TRUSTED_CONNECTION=yes",
                details={"missing_vars": ["SQLSERVER_USERNAME", "SQLSERVER_PASSWORD"]},
            )
        parts.append(f"UID={username}")
        parts.append(f"PWD={password}")

    return ";".join(parts)


# ============================================================================
# CONNECTION POOL
# ============================================================================
class ConnectionPool:
    """Pool de conexões para reutilização eficiente.
    
    Mantém conexões abertas para evitar overhead de reconexão a cada chamada.
    Thread-safe para uso em ambientes concorrentes.
    """
    
    def __init__(self, max_size: int = 5, max_idle_time: int = 300):
        """
        Args:
            max_size: Número máximo de conexões no pool
            max_idle_time: Tempo máximo (segundos) que uma conexão pode ficar ociosa
        """
        self._max_size = max_size
        self._max_idle_time = max_idle_time
        self._pool: List[tuple[pyodbc.Connection, float]] = []  # (conn, last_used_time)
        self._lock = threading.Lock()
        self._connection_string: Optional[str] = None
        self._total_created = 0
        self._total_reused = 0
        
        logger.info(f"ConnectionPool inicializado (max_size={max_size}, max_idle_time={max_idle_time}s)")
    
    def _create_connection(self) -> pyodbc.Connection:
        """Cria uma nova conexão com o banco."""
        if self._connection_string is None:
            self._connection_string = _build_connection_string()
        
        start_time = time.perf_counter()
        conn = pyodbc.connect(self._connection_string, timeout=10)
        elapsed = (time.perf_counter() - start_time) * 1000
        
        self._total_created += 1
        logger.debug(f"Nova conexão criada em {elapsed:.2f}ms (total criadas: {self._total_created})")
        
        return conn
    
    def _is_connection_valid(self, conn: pyodbc.Connection) -> bool:
        """Verifica se a conexão ainda está ativa."""
        try:
            # Executa uma query simples para verificar a conexão
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except pyodbc.Error:
            return False
    
    def _cleanup_expired(self) -> None:
        """Remove conexões expiradas do pool."""
        current_time = time.time()
        expired = []
        
        for i, (conn, last_used) in enumerate(self._pool):
            if current_time - last_used > self._max_idle_time:
                expired.append(i)
        
        # Remove do fim para o início para não bagunçar os índices
        for i in reversed(expired):
            conn, _ = self._pool.pop(i)
            try:
                conn.close()
                logger.debug(f"Conexão expirada removida do pool (idle > {self._max_idle_time}s)")
            except pyodbc.Error:
                pass
    
    def get_connection(self) -> pyodbc.Connection:
        """Obtém uma conexão do pool ou cria uma nova."""
        with self._lock:
            self._cleanup_expired()
            
            # Tenta reutilizar uma conexão do pool
            while self._pool:
                conn, last_used = self._pool.pop()
                
                if self._is_connection_valid(conn):
                    self._total_reused += 1
                    logger.debug(
                        f"Conexão reutilizada do pool "
                        f"(pool_size={len(self._pool)}, reusadas={self._total_reused})"
                    )
                    return conn
                else:
                    # Conexão inválida, fecha e tenta próxima
                    try:
                        conn.close()
                    except pyodbc.Error:
                        pass
                    logger.debug("Conexão inválida descartada do pool")
            
            # Pool vazio, cria nova conexão
            return self._create_connection()
    
    def return_connection(self, conn: pyodbc.Connection) -> None:
        """Devolve uma conexão ao pool para reutilização."""
        with self._lock:
            # Se o pool está cheio, fecha a conexão
            if len(self._pool) >= self._max_size:
                try:
                    conn.close()
                    logger.debug("Pool cheio, conexão fechada")
                except pyodbc.Error:
                    pass
                return
            
            # Verifica se a conexão ainda é válida antes de devolver
            if self._is_connection_valid(conn):
                self._pool.append((conn, time.time()))
                logger.debug(f"Conexão devolvida ao pool (pool_size={len(self._pool)})")
            else:
                try:
                    conn.close()
                except pyodbc.Error:
                    pass
                logger.debug("Conexão inválida não devolvida ao pool")
    
    def close_all(self) -> None:
        """Fecha todas as conexões do pool."""
        with self._lock:
            for conn, _ in self._pool:
                try:
                    conn.close()
                except pyodbc.Error:
                    pass
            
            closed_count = len(self._pool)
            self._pool.clear()
            logger.info(
                f"Pool encerrado: {closed_count} conexões fechadas "
                f"(total criadas: {self._total_created}, reutilizadas: {self._total_reused})"
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do pool."""
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "max_size": self._max_size,
                "total_created": self._total_created,
                "total_reused": self._total_reused,
                "reuse_rate": (
                    f"{(self._total_reused / (self._total_created + self._total_reused) * 100):.1f}%"
                    if (self._total_created + self._total_reused) > 0
                    else "0%"
                ),
            }


# Pool global de conexões
# Configurável via variáveis de ambiente
POOL_MAX_SIZE = int(os.getenv("SQLSERVER_POOL_SIZE", "5"))
POOL_MAX_IDLE_TIME = int(os.getenv("SQLSERVER_POOL_IDLE_TIME", "300"))

_connection_pool = ConnectionPool(max_size=POOL_MAX_SIZE, max_idle_time=POOL_MAX_IDLE_TIME)

# Registra fechamento do pool ao encerrar o processo
atexit.register(_connection_pool.close_all)


@contextmanager
def get_connection() -> Generator[pyodbc.Connection, None, None]:
    """Context manager para obter uma conexão do pool.
    
    Uso:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
    """
    conn = None
    start_time = time.perf_counter()
    try:
        conn = _connection_pool.get_connection()
        yield conn
    except pyodbc.Error as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"Erro de conexão após {elapsed:.2f}ms: {e}")
        raise
    finally:
        if conn is not None:
            _connection_pool.return_connection(conn)


def _rows_to_dicts(cursor: pyodbc.Cursor, rows: List[Any]) -> List[Dict[str, Any]]:
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@app.tool()
@handle_errors
def test_connection() -> Dict[str, Any]:
    """Valida a conexão com o SQL Server e retorna informações básicas do servidor."""
    logger.info("Executando test_connection")
    start_time = time.perf_counter()
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT @@VERSION AS version, DB_NAME() AS current_database;")
            result = _rows_to_dicts(cur, cur.fetchall())
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"test_connection concluído em {elapsed:.2f}ms")
            return result[0] if result else {}


@app.tool()
@handle_errors
def list_schemas() -> List[str]:
    """Lista schemas disponíveis no banco atual."""
    logger.info("Executando list_schemas")
    start_time = time.perf_counter()
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT TABLE_SCHEMA
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA
                """
            )
            rows = [r[0] for r in cur.fetchall()]
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"list_schemas retornou {len(rows)} schemas em {elapsed:.2f}ms")
            return rows


@app.tool()
@handle_errors
def list_tables(schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista tabelas. Se schema for informado, filtra por ele."""
    logger.info(f"Executando list_tables (schema={schema})")
    start_time = time.perf_counter()
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            if schema:
                cur.execute(
                    """
                    SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = ?
                    ORDER BY TABLE_SCHEMA, TABLE_NAME
                    """,
                    (schema,),
                )
            else:
                cur.execute(
                    """
                    SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    ORDER BY TABLE_SCHEMA, TABLE_NAME
                    """
                )
            result = _rows_to_dicts(cur, cur.fetchall())
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"list_tables retornou {len(result)} tabelas em {elapsed:.2f}ms")
            return result


@app.tool()
@handle_errors
def describe_table(table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Descreve colunas de uma tabela.

    - table_name: nome da tabela
    - schema: schema da tabela (opcional)
    """
    logger.info(f"Executando describe_table (table={table_name}, schema={schema})")
    
    if not table_name:
        raise ValidationError(
            "O parâmetro 'table_name' é obrigatório",
            details={"parameter": "table_name"},
        )

    start_time = time.perf_counter()
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            if schema:
                cur.execute(
                    """
                    SELECT
                        c.TABLE_SCHEMA,
                        c.TABLE_NAME,
                        c.COLUMN_NAME,
                        c.ORDINAL_POSITION,
                        c.DATA_TYPE,
                        c.CHARACTER_MAXIMUM_LENGTH,
                        c.NUMERIC_PRECISION,
                        c.NUMERIC_SCALE,
                        c.IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
                    ORDER BY c.ORDINAL_POSITION
                    """,
                    (schema, table_name),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        c.TABLE_SCHEMA,
                        c.TABLE_NAME,
                        c.COLUMN_NAME,
                        c.ORDINAL_POSITION,
                        c.DATA_TYPE,
                        c.CHARACTER_MAXIMUM_LENGTH,
                        c.NUMERIC_PRECISION,
                        c.NUMERIC_SCALE,
                        c.IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    WHERE c.TABLE_NAME = ?
                    ORDER BY c.TABLE_SCHEMA, c.ORDINAL_POSITION
                    """,
                    (table_name,),
                )
            result = _rows_to_dicts(cur, cur.fetchall())
            
            if not result:
                raise SQLServerMCPError(
                    f"Tabela '{table_name}' não encontrada" + (f" no schema '{schema}'" if schema else ""),
                    code=ErrorCode.TABLE_NOT_FOUND,
                    details={"table_name": table_name, "schema": schema},
                )
            
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"describe_table retornou {len(result)} colunas em {elapsed:.2f}ms")
            return result


# Padrão para validar que a query começa com SELECT ou WITH
_SAFE_SELECT_PATTERN = re.compile(r"^\s*(with|select)\b", re.IGNORECASE | re.DOTALL)

# Palavras-chave perigosas que indicam operações de escrita/DDL
_DANGEROUS_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|exec|execute|grant|revoke|"
    r"deny|backup|restore|shutdown|kill|reconfigure|dbcc|bulk|openrowset|opendatasource|"
    r"xp_|sp_configure|sp_executesql)\b",
    re.IGNORECASE
)

# Padrão para detectar múltiplos statements (ponto e vírgula seguido de comandos)
_MULTI_STATEMENT_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)


def _validate_readonly_query(sql: str) -> None:
    """Valida que a query é segura para execução read-only.
    
    Raises:
        ValidationError: Se a query estiver vazia.
        SecurityError: Se a query contiver comandos perigosos ou padrões suspeitos.
    """
    if not sql or not sql.strip():
        logger.warning("Tentativa de executar query vazia")
        raise ValidationError("A consulta SQL não pode estar vazia")
    
    # Verifica se começa com SELECT ou WITH
    if not _SAFE_SELECT_PATTERN.search(sql):
        logger.warning(f"Query bloqueada - não começa com SELECT/WITH: {sql[:100]}...")
        raise SecurityError(
            "Apenas consultas de leitura são permitidas (deve iniciar com SELECT ou WITH)",
            details={"query_preview": sql[:100]},
        )
    
    # Bloqueia palavras-chave perigosas
    dangerous_match = _DANGEROUS_KEYWORDS.search(sql)
    if dangerous_match:
        keyword = dangerous_match.group()
        logger.warning(f"Query bloqueada - palavra-chave perigosa '{keyword}': {sql[:100]}...")
        raise SecurityError(
            f"Comando não permitido detectado: '{keyword}'. "
            "Apenas consultas SELECT/WITH são permitidas.",
            details={"blocked_keyword": keyword, "query_preview": sql[:100]},
        )
    
    # Bloqueia múltiplos statements (previne SQL injection com ;)
    if _MULTI_STATEMENT_PATTERN.search(sql):
        logger.warning(f"Query bloqueada - múltiplos statements detectados: {sql[:100]}...")
        raise SecurityError(
            "Múltiplos statements não são permitidos. Execute apenas uma consulta SELECT por vez.",
            details={"reason": "multiple_statements", "query_preview": sql[:100]},
        )
    
    logger.debug("Query passou na validação de segurança")


@app.tool()
@handle_errors
def run_query(sql: str, max_rows: int = 1000) -> List[Dict[str, Any]]:
    """Executa uma consulta somente-LEITURA (SELECT/CTE). Limita o número de linhas retornadas.

    - sql: consulta (deve iniciar com SELECT ou WITH)
    - max_rows: máximo de linhas a retornar (padrão: 1000)
    
    Segurança:
    - Bloqueia comandos de escrita (INSERT, UPDATE, DELETE, etc.)
    - Bloqueia comandos DDL (CREATE, DROP, ALTER, etc.)
    - Bloqueia múltiplos statements (proteção contra SQL injection)
    - Executa em transação com ROLLBACK automático (nada é persistido)
    """
    # Log da query (truncada para não poluir logs)
    sql_preview = sql[:200] + "..." if len(sql) > 200 else sql
    logger.info(f"Executando run_query (max_rows={max_rows}): {sql_preview}")
    
    # Validação de segurança
    _validate_readonly_query(sql)

    if max_rows <= 0:
        max_rows = 1000

    start_time = time.perf_counter()
    
    with get_connection() as conn:
        # Desabilita autocommit para controlar a transação manualmente
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchmany(max_rows)
                result = _rows_to_dicts(cur, rows)
        finally:
            # SEMPRE faz rollback - mesmo para SELECT, garante que nada seja persistido
            # caso algum comando malicioso passe pela validação
            conn.rollback()
        
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(f"run_query retornou {len(result)} linhas em {elapsed:.2f}ms")
        return result


@app.tool()
@handle_errors
def pool_stats() -> Dict[str, Any]:
    """Retorna estatísticas do pool de conexões.
    
    Útil para monitoramento e debug de performance.
    """
    logger.info("Executando pool_stats")
    stats = _connection_pool.get_stats()
    logger.info(f"Pool stats: {stats}")
    return stats


if __name__ == "__main__":
    app.run("stdio")
