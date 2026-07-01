from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Protocol
from urllib.parse import urlparse
import uuid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanRecord:
    scan_id: str
    file_type: str
    timestamp: str
    score: int
    grade: str
    risk_count: int

    def as_dict(self) -> dict:
        return {
            "scan_id": self.scan_id,
            "file_type": self.file_type,
            "timestamp": self.timestamp,
            "score": self.score,
            "grade": self.grade,
            "risk_count": self.risk_count,
        }


class ScanStore(Protocol):
    def add_scan(self, file_type: str, result: dict) -> dict:
        ...

    def recent_scans(self, limit: int = 50) -> list[dict]:
        ...

    def summary(self) -> dict:
        ...

    def clear(self) -> None:
        ...


class MemoryScanStore:
    def __init__(self, max_history: int = 500):
        self._records: deque[ScanRecord] = deque(maxlen=max_history)

    def add_scan(self, file_type: str, result: dict) -> dict:
        record = build_scan_record(file_type, result)
        self._records.append(record)
        return record.as_dict()

    def recent_scans(self, limit: int = 50) -> list[dict]:
        return [record.as_dict() for record in list(self._records)[-limit:]]

    def summary(self) -> dict:
        records = list(self._records)
        total = len(records)
        if total == 0:
            return {"stored_scans": 0, "average_score": 0.0, "high_risk_scans": 0}
        return {
            "stored_scans": total,
            "average_score": round(sum(item.score for item in records) / total, 2),
            "high_risk_scans": sum(1 for item in records if item.score >= 50),
        }

    def clear(self) -> None:
        self._records.clear()


class MySQLScanStore:
    def __init__(self, config: dict):
        try:
            import mysql.connector
        except ImportError as exc:
            raise RuntimeError("mysql-connector-python is required for MySQL storage.") from exc

        self._mysql = mysql.connector
        self._config = config
        self._ensure_schema()

    def _connect(self):
        return self._mysql.connect(**self._config)

    def _ensure_schema(self) -> None:
        ddl = """
            CREATE TABLE IF NOT EXISTS scans (
                scan_id VARCHAR(32) PRIMARY KEY,
                file_type VARCHAR(24) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                score INT NOT NULL,
                grade VARCHAR(32) NOT NULL,
                risk_count INT NOT NULL
            )
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(ddl)
            conn.commit()

    def add_scan(self, file_type: str, result: dict) -> dict:
        record = build_scan_record(file_type, result)
        sql = """
            INSERT INTO scans (scan_id, file_type, created_at, score, grade, risk_count)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        created_at = datetime.fromisoformat(record.timestamp)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        record.scan_id,
                        record.file_type,
                        created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        record.score,
                        record.grade,
                        record.risk_count,
                    ),
                )
            conn.commit()
        return record.as_dict()

    def recent_scans(self, limit: int = 50) -> list[dict]:
        sql = """
            SELECT scan_id, file_type, created_at, score, grade, risk_count
            FROM scans
            ORDER BY created_at DESC
            LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(sql, (limit,))
                rows = cursor.fetchall()
        return [row_to_scan(row) for row in reversed(rows)]

    def summary(self) -> dict:
        sql = """
            SELECT
                COUNT(*) AS stored_scans,
                COALESCE(AVG(score), 0) AS average_score,
                COALESCE(SUM(CASE WHEN score >= 50 THEN 1 ELSE 0 END), 0) AS high_risk_scans
            FROM scans
        """
        with self._connect() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(sql)
                row = cursor.fetchone() or {}
        return {
            "stored_scans": int(row.get("stored_scans") or 0),
            "average_score": round(float(row.get("average_score") or 0), 2),
            "high_risk_scans": int(row.get("high_risk_scans") or 0),
        }

    def clear(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM scans")
            conn.commit()


def build_scan_record(file_type: str, result: dict) -> ScanRecord:
    return ScanRecord(
        scan_id=uuid.uuid4().hex[:12],
        file_type=(file_type or "image").lower(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        score=int(result["score"]),
        grade=str(result["grade"]),
        risk_count=len(result.get("risks", [])),
    )


def row_to_scan(row: dict) -> dict:
    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        timestamp = created_at.replace(tzinfo=timezone.utc).isoformat()
    else:
        timestamp = str(created_at)
    return {
        "scan_id": row["scan_id"],
        "file_type": row["file_type"],
        "timestamp": timestamp,
        "score": int(row["score"]),
        "grade": row["grade"],
        "risk_count": int(row["risk_count"]),
    }


def mysql_config_from_env() -> dict | None:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+mysqlconnector"}:
            return None
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username,
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/"),
        }

    database = os.getenv("MYSQL_DATABASE")
    user = os.getenv("MYSQL_USER")
    if not database or not user:
        return None

    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": user,
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": database,
    }


def create_scan_store() -> ScanStore:
    config = mysql_config_from_env()
    if not config:
        return MemoryScanStore()
    try:
        return MySQLScanStore(config)
    except Exception as exc:
        logger.warning("MySQL scan storage unavailable; using in-memory history: %s", exc)
        return MemoryScanStore()
