import os
import json
import logging
import asyncpg
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
_pool: Optional[asyncpg.Pool] = None

async def init_db():
    """Initializes connection pool and creates users table if missing."""
    global _pool
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is missing!")

    try:
        _pool = await asyncpg.create_pool(
            DB_URL,
            min_size=2,
            max_size=10,
            max_inactive_connection_lifetime=300.0,
            command_timeout=60
        )

        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_users_data ON users USING gin (data);
            """)
        logger.info("⚡ PostgreSQL Connection Pool Initialized & Schema Verified.")
    except Exception as e:
        logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
        raise e

async def close_db():
    """Safely closes the connection pool on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("📥 PostgreSQL Connection Pool closed safely.")

async def get_user(user_id: str) -> Dict[str, Any]:
    """Retrieves single user. Returns {} if not found."""
    global _pool
    if not _pool:
        await init_db()

    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT data FROM users WHERE user_id = $1", str(user_id))
        return json.loads(row['data']) if row else {}

async def save_user(user_id: str, data: Dict[str, Any]):
    """Atomic upsert. No collisions possible."""
    global _pool
    if not _pool:
        await init_db()

    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, data)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, str(user_id), json.dumps(data))
