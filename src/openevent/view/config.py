from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(frozen=True)
class OpenEventConfig:
    target: str = "127.0.0.1:9527"


@dataclass(frozen=True)
class HistoryConfig:
    default_limit: int = 100
    max_limit: int = 1000
    fetch_batch_size: int = 1000
    max_scan_messages: int = 10000
    default_order: str = "desc"


@dataclass(frozen=True)
class PayloadConfig:
    parse_json: bool = True
    include_text: bool = True
    text_max_bytes: int = 65536


@dataclass(frozen=True)
class ViewConfig:
    version: str
    server: ServerConfig
    openevent: OpenEventConfig
    history: HistoryConfig
    payload: PayloadConfig


def load_config(path: str | Path | None = None) -> ViewConfig:
    if path is None:
        return parse_config({})
    with Path(path).open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    return parse_config(raw or {})


def parse_config(raw: Any) -> ViewConfig:
    data = _obj(raw, "config")
    version = _str(data.get("version", "v1"), "version")
    if version != "v1":
        raise ConfigError("version must be v1")

    server_raw = _obj(data.get("server", {}), "server")
    openevent_raw = _obj(data.get("openevent", {}), "openevent")
    history_raw = _obj(data.get("history", {}), "history")
    payload_raw = _obj(data.get("payload", {}), "payload")

    history = HistoryConfig(
        default_limit=_positive_int(
            history_raw.get("default_limit", HistoryConfig.default_limit),
            "history.default_limit",
        ),
        max_limit=_positive_int(
            history_raw.get("max_limit", HistoryConfig.max_limit),
            "history.max_limit",
        ),
        fetch_batch_size=_positive_int(
            history_raw.get("fetch_batch_size", HistoryConfig.fetch_batch_size),
            "history.fetch_batch_size",
        ),
        max_scan_messages=_positive_int(
            history_raw.get("max_scan_messages", HistoryConfig.max_scan_messages),
            "history.max_scan_messages",
        ),
        default_order=_order(
            history_raw.get("default_order", HistoryConfig.default_order),
            "history.default_order",
        ),
    )
    if history.default_limit > history.max_limit:
        raise ConfigError("history.default_limit must be <= history.max_limit")
    if history.max_limit > 1000:
        raise ConfigError("history.max_limit must be <= 1000")
    if history.fetch_batch_size > 1000:
        raise ConfigError("history.fetch_batch_size must be <= 1000")

    return ViewConfig(
        version=version,
        server=ServerConfig(
            host=_str(server_raw.get("host", ServerConfig.host), "server.host"),
            port=_port(server_raw.get("port", ServerConfig.port), "server.port"),
        ),
        openevent=OpenEventConfig(
            target=_str(
                openevent_raw.get("target", OpenEventConfig.target),
                "openevent.target",
            ),
        ),
        history=history,
        payload=PayloadConfig(
            parse_json=_bool(
                payload_raw.get("parse_json", PayloadConfig.parse_json),
                "payload.parse_json",
            ),
            include_text=_bool(
                payload_raw.get("include_text", PayloadConfig.include_text),
                "payload.include_text",
            ),
            text_max_bytes=_positive_int(
                payload_raw.get("text_max_bytes", PayloadConfig.text_max_bytes),
                "payload.text_max_bytes",
            ),
        ),
    )


def _obj(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    return value


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _port(value: Any, field: str) -> int:
    port = _positive_int(value, field)
    if port > 65535:
        raise ConfigError(f"{field} must be between 1 and 65535")
    return port


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a boolean")
    return value


def _order(value: Any, field: str) -> str:
    value = _str(value, field)
    if value not in {"asc", "desc"}:
        raise ConfigError(f"{field} must be asc or desc")
    return value
