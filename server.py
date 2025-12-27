import atexit
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import pyodbc
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


load_dotenv()

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
        raise ValueError("A variável de ambiente SQLSERVER_SERVER é obrigatória")

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
            raise ValueError(
                "Defina SQLSERVER_USERNAME e SQLSERVER_PASSWORD ou habilite SQLSERVER_TRUSTED_CONNECTION=yes"
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
def test_connection() -> Dict[str, Any]:
    """Valida a conexão com o SQL Server e retorna informações básicas do servidor."""
    logger.info("Executando test_connection")
    start_time = time.perf_counter()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT @@VERSION AS version, DB_NAME() AS current_database;")
                result = _rows_to_dicts(cur, cur.fetchall())
                elapsed = (time.perf_counter() - start_time) * 1000
                logger.info(f"test_connection concluído em {elapsed:.2f}ms")
                return result[0] if result else {}
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"test_connection falhou após {elapsed:.2f}ms: {e}")
        raise


@app.tool()
def list_schemas() -> List[str]:
    """Lista schemas disponíveis no banco atual."""
    logger.info("Executando list_schemas")
    start_time = time.perf_counter()
    try:
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
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"list_schemas falhou após {elapsed:.2f}ms: {e}")
        raise


@app.tool()
def list_tables(schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista tabelas. Se schema for informado, filtra por ele."""
    logger.info(f"Executando list_tables (schema={schema})")
    start_time = time.perf_counter()
    try:
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
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"list_tables falhou após {elapsed:.2f}ms: {e}")
        raise


@app.tool()
def describe_table(table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Descreve colunas de uma tabela.

    - table_name: nome da tabela
    - schema: schema da tabela (opcional)
    """
    logger.info(f"Executando describe_table (table={table_name}, schema={schema})")
    
    if not table_name:
        logger.warning("describe_table chamado sem table_name")
        raise ValueError("'table_name' é obrigatório")

    start_time = time.perf_counter()
    try:
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
                elapsed = (time.perf_counter() - start_time) * 1000
                logger.info(f"describe_table retornou {len(result)} colunas em {elapsed:.2f}ms")
                return result
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"describe_table falhou após {elapsed:.2f}ms: {e}")
        raise


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
        ValueError: Se a query contiver comandos perigosos ou padrões suspeitos.
    """
    if not sql or not sql.strip():
        logger.warning("Tentativa de executar query vazia")
        raise ValueError("A consulta SQL não pode estar vazia")
    
    # Verifica se começa com SELECT ou WITH
    if not _SAFE_SELECT_PATTERN.search(sql):
        logger.warning(f"Query bloqueada - não começa com SELECT/WITH: {sql[:100]}...")
        raise ValueError("Apenas consultas de leitura são permitidas (deve iniciar com SELECT ou WITH)")
    
    # Bloqueia palavras-chave perigosas
    dangerous_match = _DANGEROUS_KEYWORDS.search(sql)
    if dangerous_match:
        logger.warning(
            f"Query bloqueada - palavra-chave perigosa '{dangerous_match.group()}': {sql[:100]}..."
        )
        raise ValueError(
            f"Comando não permitido detectado: '{dangerous_match.group()}'. "
            "Apenas consultas SELECT/WITH são permitidas."
        )
    
    # Bloqueia múltiplos statements (previne SQL injection com ;)
    if _MULTI_STATEMENT_PATTERN.search(sql):
        logger.warning(f"Query bloqueada - múltiplos statements detectados: {sql[:100]}...")
        raise ValueError(
            "Múltiplos statements não são permitidos. "
            "Execute apenas uma consulta SELECT por vez."
        )
    
    logger.debug("Query passou na validação de segurança")


@app.tool()
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
    try:
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
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"run_query falhou após {elapsed:.2f}ms: {e}")
        raise


@app.tool()
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
