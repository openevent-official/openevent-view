from __future__ import annotations

import base64
import codecs
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol

import grpc

from .config import HistoryConfig


UINT64_MAX = 2**64 - 1
INLINE_PAYLOAD_BYTES = 16 * 1024
PREVIEW_PART_BYTES = 8 * 1024
_UINT64_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\Z")


class RequestError(ValueError):
    code = "INVALID_ARGUMENT"


class UpstreamProtocolError(RuntimeError):
    code = "BAD_GATEWAY"


class MessageNotFound(LookupError):
    code = "NOT_FOUND"


class QueryTimeout(RuntimeError):
    code = "QUERY_TIMEOUT"


class QueryDeadline:
    def __init__(self, seconds: float):
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        remaining = self._end - time.monotonic()
        if remaining <= 0:
            raise QueryTimeout("history query timed out")
        return remaining


class OpenEventClientProtocol(Protocol):
    def get_status(self, principal: int, token: str, *, timeout: float) -> Any: ...

    def get_channel(self, principal: int, token: str, channel_id: int, *, timeout: float) -> Any: ...

    def fetch(
        self,
        principal: int,
        token: str,
        from_seq: int,
        limit: int,
        only_my_recipient: bool = False,
        channels: tuple[int, ...] = (),
        *,
        timeout: float,
    ) -> Any: ...


@dataclass(frozen=True)
class HistoryQuery:
    principal: int
    token: str
    before_seq: int | None
    limit: int
    channel_id: int | None
    only_my_recipient: bool


@dataclass(frozen=True)
class PayloadQuery:
    principal: int
    token: str


@dataclass(frozen=True)
class ChannelDisplay:
    channel_id: int
    name: str
    protocol: str

    def to_dict(self) -> dict[str, str]:
        return {
            "channel_id": str(self.channel_id),
            "channel_name": self.name,
            "channel_protocol": self.protocol,
        }


class HistoryService:
    def __init__(
        self,
        client: OpenEventClientProtocol,
        history_config: HistoryConfig,
        channel_cache_size: int = 4096,
        channel_lookup_workers: int = 8,
        query_timeout_seconds: float = 30.0,
        rpc_timeout_seconds: float = 10.0,
    ):
        self._client = client
        self._history = history_config
        self._query_timeout_seconds = query_timeout_seconds
        self._rpc_timeout_seconds = rpc_timeout_seconds
        self._channel_cache_size = channel_cache_size
        self._channel_cache: OrderedDict[tuple[int, int], ChannelDisplay] = (
            OrderedDict()
        )
        self._channel_cache_lock = threading.Lock()
        self._channel_executor = ThreadPoolExecutor(
            max_workers=channel_lookup_workers,
            thread_name_prefix="openevent-view-channel",
        )

    def close(self) -> None:
        self._channel_executor.shutdown(wait=True, cancel_futures=True)

    def query(self, query: HistoryQuery) -> dict[str, Any]:
        deadline = QueryDeadline(self._query_timeout_seconds)
        status = self._call(deadline, self._client.get_status, query.principal, query.token)
        min_seq = int(status.min_seq)
        max_seq = int(status.max_seq)
        messages: list[dict[str, Any]] = []
        fetch_performed = False
        history_complete = True

        if query.before_seq != 0:
            end_seq = max_seq
            if query.before_seq is not None:
                end_seq = min(end_seq, query.before_seq - 1)
            if end_seq >= min_seq:
                messages, fetch_performed, history_complete = self._query_descending(
                    query, min_seq, end_seq, deadline
                )

        channel_ids = {int(message["channel_id"]) for message in messages}
        if query.channel_id is not None:
            channel_ids.add(query.channel_id)
        displays = self._load_channel_displays(
            query.principal,
            query.token,
            channel_ids,
            deadline,
            force_channel_id=(
                query.channel_id
                if query.channel_id is not None and not fetch_performed
                else None
            ),
        )

        for message in messages:
            message.update(displays[int(message["channel_id"])].to_dict())
        deadline.remaining()
        result: dict[str, Any] = {
            "messages": messages,
            "next_cursor": self._next_cursor(messages, history_complete),
        }
        if query.channel_id is not None:
            result["channel"] = displays[query.channel_id].to_dict()
        return result

    def get_payload(self, seq: int, query: PayloadQuery) -> dict[str, Any]:
        deadline = QueryDeadline(self._query_timeout_seconds)
        status = self._call(deadline, self._client.get_status, query.principal, query.token)
        min_seq = int(status.min_seq)
        max_seq = int(status.max_seq)
        if seq < min_seq or seq > max_seq:
            raise MessageNotFound("message not found")

        try:
            response = self._call(
                deadline, self._client.fetch,
                query.principal, query.token, from_seq=seq, limit=1,
                only_my_recipient=False, channels=(),
            )
            if int(response.next_seq) <= seq:
                raise UpstreamProtocolError("OpenEvent Fetch next_seq did not advance")
            for message in response.messages:
                if int(message.seq) == seq:
                    displays = self._load_channel_displays(
                        query.principal, query.token, {int(message.channel_id)}, deadline,
                    )
                    result = self._message_to_dict(message, full_payload=True)
                    result.update(displays[int(message.channel_id)].to_dict())
                    deadline.remaining()
                    return {"message": result}
        except grpc.RpcError as exc:
            if exc.code() in {grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.NOT_FOUND}:
                raise MessageNotFound("message not found") from exc
            raise
        raise MessageNotFound("message not found")

    def _call(self, deadline: QueryDeadline, method, *args, **kwargs):
        timeout = min(self._rpc_timeout_seconds, deadline.remaining())
        try:
            result = method(*args, **kwargs, timeout=timeout)
        except grpc.RpcError:
            deadline.remaining()
            raise
        deadline.remaining()
        return result

    def _query_descending(
        self, query: HistoryQuery, min_seq: int, end_seq: int, deadline: QueryDeadline
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        collected: list[dict[str, Any]] = []
        window_end = end_seq
        channels = (query.channel_id,) if query.channel_id is not None else ()
        fetch_performed = False
        history_complete = False

        while window_end >= min_seq and len(collected) < query.limit:
            deadline.remaining()
            remaining = query.limit - len(collected)
            window_size = self._history.fetch_batch_size
            window_start = max(min_seq, window_end - window_size + 1)
            window_messages, matched_count = self._fetch_window(
                query,
                channels,
                window_start,
                window_end,
                window_size,
                remaining,
                deadline,
            )
            fetch_performed = True
            collected.extend(window_messages)
            history_complete = window_start == min_seq and matched_count <= remaining
            window_end = window_start - 1

        return collected, fetch_performed, history_complete

    def _fetch_window(
        self,
        query: HistoryQuery,
        channels: tuple[int, ...],
        window_start: int,
        window_end: int,
        window_size: int,
        candidate_limit: int,
        deadline: QueryDeadline,
    ) -> tuple[list[dict[str, Any]], int]:
        fetch_from = window_start
        messages: list[dict[str, Any]] = []
        matched_count = 0
        while fetch_from <= window_end:
            response = self._call(
                deadline, self._client.fetch,
                query.principal,
                query.token,
                from_seq=fetch_from,
                limit=window_size,
                only_my_recipient=query.only_my_recipient,
                channels=channels,
            )
            next_seq = int(response.next_seq)
            if next_seq <= fetch_from:
                raise UpstreamProtocolError("OpenEvent Fetch next_seq did not advance")
            candidates = [
                message for message in response.messages
                if window_start <= int(message.seq) <= window_end
            ]
            matched_count += len(candidates)
            candidates.sort(key=lambda message: int(message.seq), reverse=True)
            # Older entries in this response cannot make the page. Select before
            # decoding payloads, while still scanning every response in the window.
            for message in candidates[:candidate_limit]:
                deadline.remaining()
                messages.append(self._message_to_dict(message, full_payload=False))
            messages.sort(key=lambda message: int(message["seq"]), reverse=True)
            del messages[candidate_limit:]
            # Keep only the projections; release the RPC payload before the next Fetch.
            message = None
            del candidates
            del response
            fetch_from = next_seq
        return messages, matched_count

    @staticmethod
    def _next_cursor(
        messages: list[dict[str, Any]], history_complete: bool
    ) -> dict[str, str] | None:
        if history_complete or not messages:
            return None
        before_seq = int(messages[-1]["seq"])
        return {"before_seq": str(before_seq)}

    def _message_to_dict(
        self,
        message: Any,
        *,
        full_payload: bool,
    ) -> dict[str, Any]:
        channel_id = int(message.channel_id)
        return {
            "seq": str(int(message.seq)),
            "uuid": str(int(message.uuid)),
            "ts_ms": str(int(message.ts_ms)),
            "channel_id": str(channel_id),
            "principal": str(int(message.principal)),
            "recipients": [str(int(item)) for item in message.recipients],
            "object_ids": [
                str(int(object_key.object_id)) for object_key in message.object_keys
            ],
            "payload": encode_payload(bytes(message.payload), full=full_payload),
        }

    def _load_channel_displays(
        self,
        principal: int,
        token: str,
        channel_ids: set[int],
        deadline: QueryDeadline,
        force_channel_id: int | None = None,
    ) -> dict[int, ChannelDisplay]:
        displays: dict[int, ChannelDisplay] = {}
        missing: list[int] = []
        for channel_id in sorted(channel_ids):
            deadline.remaining()
            cached = None
            if channel_id != force_channel_id:
                cached = self._get_cached_channel(principal, channel_id)
            if cached is None:
                missing.append(channel_id)
            else:
                displays[channel_id] = cached

        futures = {
            channel_id: self._channel_executor.submit(
                self._get_channel, principal, token, channel_id, deadline
            )
            for channel_id in missing
        }
        try:
            for channel_id, future in futures.items():
                try:
                    display = future.result(timeout=deadline.remaining())
                except FutureTimeoutError as exc:
                    raise QueryTimeout("history query timed out") from exc
                displays[channel_id] = display
                self._cache_channel(principal, display)
        finally:
            for future in futures.values():
                future.cancel()
        return displays

    def _get_channel(
        self, principal: int, token: str, channel_id: int, deadline: QueryDeadline
    ) -> ChannelDisplay:
        response = self._call(deadline, self._client.get_channel, principal, token, channel_id)
        return ChannelDisplay(
            channel_id=channel_id,
            name=str(response.channel.name),
            protocol=str(response.channel.protocol),
        )

    def _get_cached_channel(
        self, principal: int, channel_id: int
    ) -> ChannelDisplay | None:
        key = (principal, channel_id)
        with self._channel_cache_lock:
            display = self._channel_cache.get(key)
            if display is not None:
                self._channel_cache.move_to_end(key)
            return display

    def _cache_channel(self, principal: int, display: ChannelDisplay) -> None:
        key = (principal, display.channel_id)
        with self._channel_cache_lock:
            self._channel_cache[key] = display
            self._channel_cache.move_to_end(key)
            while len(self._channel_cache) > self._channel_cache_size:
                self._channel_cache.popitem(last=False)


def parse_history_query(data: dict[str, Any], config: HistoryConfig) -> HistoryQuery:
    principal = _required_uint64_text(data.get("principal"), "principal", positive=True)
    token = _required_string(data.get("token"), "token")
    before_seq = _parse_cursor(data.get("cursor"))

    limit = data.get("limit", config.default_limit)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > config.max_limit
    ):
        raise RequestError(
            f"limit must be an integer between 1 and {config.max_limit}"
        )

    channel_id = None
    if data.get("channel_id") is not None:
        channel_id = _required_uint64_text(data["channel_id"], "channel_id")

    only_my_recipient = data.get("only_my_recipient", False)
    if not isinstance(only_my_recipient, bool):
        raise RequestError("only_my_recipient must be a boolean")

    return HistoryQuery(
        principal=principal,
        token=token,
        before_seq=before_seq,
        limit=limit,
        channel_id=channel_id,
        only_my_recipient=only_my_recipient,
    )


def parse_payload_query(data: dict[str, Any]) -> PayloadQuery:
    return PayloadQuery(
        principal=_required_uint64_text(data.get("principal"), "principal", positive=True),
        token=_required_string(data.get("token"), "token"),
    )


def parse_seq(value: Any, field: str = "seq") -> int:
    return _required_uint64_text(value, field)


def encode_payload(payload: bytes, *, full: bool = False) -> dict[str, Any]:
    size = len(payload)
    if full or size <= INLINE_PAYLOAD_BYTES:
        return _encode_complete_payload(payload)

    utf8 = _is_utf8(payload)
    head_bytes = payload[:PREVIEW_PART_BYTES]
    tail_bytes = payload[-PREVIEW_PART_BYTES:]
    if utf8:
        head_bytes = _valid_utf8_prefix(head_bytes)
        tail_bytes = _valid_utf8_suffix(tail_bytes)
        head = head_bytes.decode("utf-8")
        tail = tail_bytes.decode("utf-8")
        encoding = "utf-8"
    else:
        head = base64.b64encode(head_bytes).decode("ascii")
        tail = base64.b64encode(tail_bytes).decode("ascii")
        encoding = "base64"

    return {
        "encoding": encoding,
        "truncated": True,
        "size_bytes": size,
        "preview": {
            "head": head,
            "tail": tail,
            "head_bytes": len(head_bytes),
            "tail_bytes": len(tail_bytes),
            "omitted_bytes": size - len(head_bytes) - len(tail_bytes),
        },
    }


def _encode_complete_payload(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "encoding": "utf-8",
        "truncated": False,
        "size_bytes": len(payload),
    }
    try:
        result["text"] = payload.decode("utf-8")
    except UnicodeDecodeError:
        result["encoding"] = "base64"
        result["text"] = base64.b64encode(payload).decode("ascii")
    return result


def _is_utf8(payload: bytes) -> bool:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        for offset in range(0, len(payload), PREVIEW_PART_BYTES):
            decoder.decode(payload[offset : offset + PREVIEW_PART_BYTES], final=False)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def _valid_utf8_prefix(value: bytes) -> bytes:
    end = len(value)
    while True:
        try:
            value[:end].decode("utf-8")
            return value[:end]
        except UnicodeDecodeError as exc:
            end = exc.start


def _valid_utf8_suffix(value: bytes) -> bytes:
    start = 0
    while True:
        try:
            value[start:].decode("utf-8")
            return value[start:]
        except UnicodeDecodeError as exc:
            start += max(exc.end, 1)


def _parse_cursor(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"before_seq"}:
        raise RequestError("cursor must be null or an object containing only before_seq")
    return _required_uint64_text(value["before_seq"], "cursor.before_seq")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RequestError(f"{field} must be a non-empty string")
    return value


def _required_uint64_text(value: Any, field: str, *, positive: bool = False) -> int:
    if not isinstance(value, str) or len(value) > 20 or _UINT64_TEXT.fullmatch(value) is None:
        raise RequestError(f"{field} must be a canonical uint64 decimal string")
    parsed = int(value)
    if parsed > UINT64_MAX or (positive and parsed == 0):
        raise RequestError(f"{field} must be a canonical uint64 decimal string")
    return parsed
