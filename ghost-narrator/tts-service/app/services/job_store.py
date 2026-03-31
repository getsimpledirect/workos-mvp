# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Job storage abstraction layer.

Provides a unified interface for job storage with Redis as primary
backend and in-memory fallback for development/resilience.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from app.config import REDIS_JOB_TTL, REDIS_URL

logger = logging.getLogger(__name__)


class JobStore:
    """
    Abstraction layer for job storage with Redis primary and in-memory fallback.

    This class provides a unified interface for storing, retrieving, and managing
    TTS job data. It attempts to use Redis as the primary storage backend, with
    automatic fallback to in-memory storage if Redis is unavailable.

    Attributes:
        use_redis: Whether Redis is currently being used.
        redis_client: The async Redis client (if connected).
        memory_store: In-memory fallback storage.
        lock: Async lock for thread-safe memory operations.
    """

    def __init__(self) -> None:
        """Initialize JobStore with default settings."""
        self.use_redis: bool = False
        self.redis_client: Optional[redis.Redis] = None
        self.memory_store: dict[str, dict[str, Any]] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self._initialized: bool = False

    async def initialize(self, redis_url: Optional[str] = None) -> None:
        """
        Initialize Redis connection with fallback to in-memory.

        Args:
            redis_url: Optional Redis URL. Defaults to REDIS_URL from config.
        """
        if self._initialized:
            logger.debug("JobStore already initialized")
            return

        url = redis_url or REDIS_URL

        try:
            self.redis_client = redis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self.redis_client.ping()
            self.use_redis = True
            self._initialized = True
            logger.info("Redis connected successfully - using persistent job storage")
        except Exception as exc:
            logger.warning(
                f"Redis connection failed: {exc}. "
                "Using in-memory storage (jobs will be lost on restart)"
            )
            self.use_redis = False
            self.redis_client = None
            self._initialized = True

    def _make_serializable(self, job_data: dict[str, Any]) -> dict[str, Any]:
        """
        Convert job data to JSON-serializable format.

        Args:
            job_data: The job data dictionary to convert.

        Returns:
            A dictionary with all values converted to JSON-serializable types.
        """
        serializable_data: dict[str, Any] = {}

        for key, value in job_data.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                serializable_data[key] = value
            elif isinstance(value, (list, dict)):
                serializable_data[key] = value
            else:
                serializable_data[key] = str(value)

        return serializable_data

    async def set(self, job_id: str, job_data: dict[str, Any]) -> None:
        """
        Store job data with TTL.

        Args:
            job_id: The unique job identifier.
            job_data: Dictionary containing job data.

        Raises:
            ValueError: If job_id is empty or job_data is not a dict.
        """
        if not job_id:
            raise ValueError("job_id cannot be empty")
        if not isinstance(job_data, dict):
            raise ValueError(f"job_data must be a dict, got {type(job_data)}")

        serializable_data = self._make_serializable(job_data)

        if self.use_redis and self.redis_client:
            try:
                await self.redis_client.setex(
                    f"job:{job_id}",
                    REDIS_JOB_TTL,
                    json.dumps(serializable_data, default=str),
                )
                return
            except Exception as exc:
                logger.error(
                    f"Redis set failed for job {job_id}: {exc}. "
                    "Using in-memory fallback for this operation (Redis connection preserved)"
                )
                # Do NOT permanently disable Redis — this may be a transient error.
                # Fall through to memory store for this write only.

        async with self.lock:
            self.memory_store[job_id] = serializable_data

    async def get(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve job data.

        Args:
            job_id: The unique job identifier.

        Returns:
            Job data dictionary if found, None otherwise.
        """
        if self.use_redis and self.redis_client:
            try:
                data = await self.redis_client.get(f"job:{job_id}")
                if data:
                    return json.loads(data)
                return None
            except Exception as exc:
                logger.error(
                    f"Redis get failed for job {job_id}: {exc}. Checking memory"
                )
                async with self.lock:
                    return self.memory_store.get(job_id)

        async with self.lock:
            return self.memory_store.get(job_id)

    async def exists(self, job_id: str) -> bool:
        """
        Check if job exists.

        Args:
            job_id: The unique job identifier.

        Returns:
            True if job exists, False otherwise.
        """
        if self.use_redis and self.redis_client:
            try:
                exists = await self.redis_client.exists(f"job:{job_id}")
                return bool(exists)
            except Exception as exc:
                logger.error(
                    f"Redis exists failed for job {job_id}: {exc}. Checking memory"
                )
                async with self.lock:
                    return job_id in self.memory_store

        async with self.lock:
            return job_id in self.memory_store

    async def create_if_not_exists(self, job_id: str, job_data: dict[str, Any]) -> bool:
        """
        Atomically create a job if it does not already exist.

        Args:
            job_id: The unique job identifier.
            job_data: Dictionary containing initial job data.

        Returns:
            True if created, False if it already existed.
        """
        if not job_id:
            raise ValueError("job_id cannot be empty")

        serializable_data = self._make_serializable(job_data)

        if self.use_redis and self.redis_client:
            try:
                # Use SET NX EX for atomic create-with-TTL (avoids setnx+expire race)
                created = await self.redis_client.set(
                    f"job:{job_id}",
                    json.dumps(serializable_data, default=str),
                    nx=True,
                    ex=REDIS_JOB_TTL,
                )
                return created is not None
            except Exception as exc:
                logger.error(
                    f"Redis create_if_not_exists failed: {exc}. "
                    "Using in-memory fallback for this operation (Redis connection preserved)"
                )
                # Do NOT permanently disable Redis — this may be a transient error.

        async with self.lock:
            if job_id in self.memory_store:
                return False
            self.memory_store[job_id] = serializable_data
            return True

    async def update(self, job_id: str, updates: dict[str, Any]) -> None:
        """
        Update job data atomically.

        Args:
            job_id: The unique job identifier.
            updates: Dictionary of fields to update.
        """
        if not updates:
            return

        serializable_updates = self._make_serializable(updates)

        if self.use_redis and self.redis_client:
            try:
                # Redis doesn't have a direct JSON merge command in standard Redis (without RedisJSON module)
                # But we are storing the whole dict as a JSON string.
                # To make it atomic without RedisJSON, we should ideally use a Lua script.
                lua_script = """
                local data = redis.call('GET', KEYS[1])
                if data then
                    local decoded = cjson.decode(data)
                    local updates = cjson.decode(ARGV[1])
                    for k, v in pairs(updates) do
                        decoded[k] = v
                    end
                    redis.call('SET', KEYS[1], cjson.encode(decoded))
                    redis.call('EXPIRE', KEYS[1], ARGV[2])
                    return 1
                end
                return 0
                """

                result = await self.redis_client.eval(
                    lua_script,
                    1,
                    f"job:{job_id}",
                    json.dumps(serializable_updates, default=str),
                    REDIS_JOB_TTL,
                )

                if result == 1:
                    return
                else:
                    logger.warning(f"Cannot update non-existent job in Redis: {job_id}")
                    return
            except Exception as exc:
                logger.error(
                    f"Redis update failed: {exc}. Falling back to non-atomic memory update"
                )
                # Fallback to in-memory

        async with self.lock:
            job_data = self.memory_store.get(job_id)
            if job_data is None:
                logger.warning(f"Cannot update non-existent job in memory: {job_id}")
                return
            job_data.update(serializable_updates)
            self.memory_store[job_id] = job_data

    async def delete(self, job_id: str) -> bool:
        """
        Delete a job from the store.

        Args:
            job_id: The unique job identifier.

        Returns:
            True if job was deleted, False if it didn't exist.
        """
        if self.use_redis and self.redis_client:
            try:
                result = await self.redis_client.delete(f"job:{job_id}")
                return bool(result)
            except Exception as exc:
                logger.error(
                    f"Redis delete failed for job {job_id}: {exc}. Deleting from memory"
                )
                async with self.lock:
                    return self.memory_store.pop(job_id, None) is not None

        async with self.lock:
            return self.memory_store.pop(job_id, None) is not None

    async def list_all(self) -> dict[str, dict[str, Any]]:
        """
        List all jobs.

        Returns:
            Dictionary mapping job_id to job data.
        """
        if self.use_redis and self.redis_client:
            try:
                keys = await self.redis_client.keys("job:*")
                if not keys:
                    return {}
                values = await self.redis_client.mget(*keys)
                jobs: dict[str, dict[str, Any]] = {}
                for key, data in zip(keys, values):
                    if data:
                        job_id = key.replace("job:", "", 1)
                        jobs[job_id] = json.loads(data)
                return jobs
            except Exception as exc:
                logger.error(f"Redis list failed: {exc}. Returning memory store")
                async with self.lock:
                    return self.memory_store.copy()

        async with self.lock:
            return self.memory_store.copy()

    async def count(self) -> int:
        """
        Get the total number of jobs.

        Returns:
            Number of jobs in the store.
        """
        if self.use_redis and self.redis_client:
            try:
                keys = await self.redis_client.keys("job:*")
                return len(keys)
            except Exception as exc:
                logger.error(f"Redis count failed: {exc}. Counting memory store")
                async with self.lock:
                    return len(self.memory_store)

        async with self.lock:
            return len(self.memory_store)

    async def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("Redis connection closed")
            except Exception as exc:
                logger.error(f"Error closing Redis connection: {exc}")
            finally:
                self.redis_client = None
                self.use_redis = False

        self._initialized = False

    @property
    def storage_type(self) -> str:
        """Get the current storage backend type."""
        return "redis" if self.use_redis else "memory"


# Global singleton instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """
    Get the global JobStore singleton instance.

    Returns:
        The JobStore singleton instance.
    """
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store


async def initialize_job_store(redis_url: Optional[str] = None) -> JobStore:
    """
    Initialize the global JobStore instance.

    Args:
        redis_url: Optional Redis URL.

    Returns:
        The initialized JobStore instance.
    """
    store = get_job_store()
    await store.initialize(redis_url)
    return store
