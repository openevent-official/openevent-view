# OpenEvent View Reference

[中文版](REFERENCE_cn.md)

This document is the authoritative reference for View configuration, HTTP APIs,
and deployment boundaries. See the [README](../README.md) for installation and
startup, and the [OpenEvent API](../openevent-sdk/docs/API.md) for upstream history,
authentication, and permission semantics. View is a read-only tool that uses
`openevent-sdk>=0.8.0` installed in the Python environment running the deployment;
it does not read server storage directly.

## 1. Deployment Boundary

View targets trusted internal networks and listens on localhost by default.
Requests use the caller's OpenEvent `principal/token`; there is no administrator
proxy identity, message publishing, or Channel mutation API. For other networks,
the deployment supplies suitable access control, TLS, traffic management, and
logging policies. View does not include these gateway facilities.

Both message APIs accept credentials only in the JSON body, not URLs,
authentication headers, cookies, or server sessions. Credentials are not written
to logs or browser storage. A page can hold its active query credentials in memory
until the query state is replaced or the page closes. A detail page opens in a new
tab and receives credentials through same-origin window messages. Opening it
directly, a failed handoff, or a handoff exceeding 5 seconds requires entering
credentials again. If a new tab is blocked, the list stays unchanged and asks the
user to allow popups and retry.

View does not cache messages or payloads across requests; its only cache is bounded
Channel display metadata. Successful and failed message responses use
`Cache-Control: no-store`. SDK `object_keys` are projected to `object_ids`, preserving
order and duplicates. `object_token` never enters HTTP responses, HTML, page state,
or logs. This rule does not interpret or modify opaque payload contents.

## 2. Configuration

Omitting the configuration file or individual fields uses these defaults:

```yaml
version: v1

server:
  host: 127.0.0.1
  port: 8080
  request_timeout_seconds: 10
  query_timeout_seconds: 30
  max_request_body_bytes: 65536

openevent:
  target: 127.0.0.1:9527
  rpc_timeout_seconds: 10
  channel_cache_size: 4096
  channel_lookup_workers: 8

history:
  default_limit: 100
  max_limit: 1000
  fetch_batch_size: 1000
```

| Field | Meaning and range |
| --- | --- |
| `version` | Must be `v1` |
| `server.host` | Nonempty HTTP listen address |
| `server.port` | HTTP port, integer `1..65535` |
| `server.request_timeout_seconds` | HTTP socket read/write timeout, finite positive number of seconds |
| `server.query_timeout_seconds` | Total history/detail query budget, finite positive number of seconds; covers authentication, Fetch, scanning, message projection, and Channel calls and queueing |
| `server.max_request_body_bytes` | POST body byte limit, positive integer |
| `openevent.target` | Nonempty OpenEvent gRPC address |
| `openevent.rpc_timeout_seconds` | Maximum wait for one OpenEvent RPC, finite positive number of seconds; also limited by the remaining query budget |
| `openevent.channel_cache_size` | Maximum Channel display metadata LRU entries, positive integer |
| `openevent.channel_lookup_workers` | Global Channel lookup concurrency, integer `1..64` |
| `history.default_limit` | Default API page size, integer `1..history.max_limit` |
| `history.max_limit` | Maximum API page size, integer `1..1000` |
| `history.fetch_batch_size` | Fixed scan window seq span and each `Fetch.limit`, integer `1..1000` |

Integer and numeric settings reject booleans. Configuration must satisfy
`1 <= history.default_limit <= history.max_limit <= 1000`; invalid configuration
prevents startup. `history.max_limit` may exceed `history.fetch_batch_size`, in
which case a page scans multiple windows. Sparse filtered results use the same
window size until the page is full, the history boundary is reached, or the query budget expires.

The HTTP socket timeout, individual RPC timeout, and total query budget are
separate limits. The query budget is checked at RPC, scanning, projection, and
Channel wait boundaries; it does not forcibly interrupt an individual CPU conversion
operation. Expiry returns `504 QUERY_TIMEOUT`, without a partial page. The built-in
browser pages have a separate fixed 35-second request limit. Increasing the server
budget does not increase this browser limit; scripts using longer budgets must set
their own HTTP timeout accordingly.

## 3. Pages

`GET /` serves the history list; `GET /message?seq=123` serves the complete payload
page. The detail URL contains only a canonical decimal seq, including valid
`seq=0`, and never credentials.

The list orders messages by descending seq, supports Channel and recipient filters,
and includes system messages visible to the caller. It uses the server's default
page size and does not expose `from_seq`, `limit`, or cursor inputs. Next loads
older messages, Previous queries an already visited newer page again, and Latest
queries the newest page again. Repeated queries can change with appended messages
or permission changes. New messages are not inserted automatically.

Editing inputs does not change the displayed results' query conditions; only a
successful Query replaces the active state. Pagination, Latest, and complete
content use the current results' credentials and conditions. A request keeps the
old results visible and replaces them together only on success. Failure or
timeout preserves results and pagination, displays the reason, and restores
controls. Each page performs one operation at a time and automatically stops
waiting after 35 seconds; closing the page also abandons the wait. Browser
cancellation does not guarantee that server work immediately
stops; the server still applies its own query budget.

Messages display their top-level metadata and payload, with the payload encoding
and original byte count also shown for list previews. The browser attempts to
render complete UTF-8 text as JSON. Successful parsing shows a tree by default,
with a switch to the original text; failures show the original text directly.
JSON objects and arrays expand on demand, showing 100 direct children per batch
and a Show more control for the rest. The tree follows JavaScript number rules
and may not preserve large integers exactly; use the original text to verify content.
Large payloads show a list preview and open complete content in a new tab.
External fields and errors are rendered as text or JSON nodes, never HTML or scripts.

## 4. HTTP API

### 4.1 Common Rules

Requests are POST JSON objects with `Content-Length`, parsed using `orjson.loads`.
Invalid JSON or a non-object top level returns `400 INVALID_ARGUMENT`. There is no
authenticated GET variant.

All OpenEvent uint64 values (IDs, seqs, timestamps, recipients, and cursor values)
are canonical decimal strings: `"0"` or digits without a leading zero, up to
`"18446744073709551615"`. Signs, spaces, and leading zeroes are invalid. The caller's
request `principal` must be positive; `channel_id`, detail `seq`, and
`cursor.before_seq` allow zero. Bounded counts such as `limit` and payload byte
sizes use JSON numbers. This rule does not change numbers inside opaque payloads.

Every history and detail query first calls `GetStatus` with that request's
`principal/token`. Invalid credentials return `401` even at a history boundary.
`min_seq=0` is a valid initialized state; `max_seq=0` means only the initialization
message exists, not empty history. View can display seq 0 and messages in Channel 0;
OpenEvent still determines visibility.

### 4.2 Query History

```http
POST /v1/messages
Content-Type: application/json

{
  "principal": "10001",
  "token": "tok_xxx",
  "cursor": null,
  "limit": 100,
  "channel_id": "10001",
  "only_my_recipient": false
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `principal` | Yes | Positive uint64 decimal string identifying the caller |
| `token` | Yes | Nonempty credential string |
| `cursor` | No | Omitted or `null` reads the newest page; otherwise an object containing only `before_seq` |
| `limit` | No | Integer `1..history.max_limit`, not boolean; defaults to `history.default_limit` |
| `channel_id` | No | uint64 decimal string; omitted or `null` means no Channel filter |
| `only_my_recipient` | No | Boolean, default `false`, forwarded to OpenEvent Fetch |

The only non-null cursor format is `{"before_seq":"123"}`, meaning read only
`seq < 123`. Missing or extra cursor fields are invalid. `{"before_seq":"0"}` is
valid and returns an empty page after successful authentication. A cursor records
only a position, not credentials, filters, or page size; each request uses its own
parameters. When both Channel and recipient filters are provided, both must match.

Response `messages` are ordered by descending seq. Pass a non-null `next_cursor`
unchanged to continue reading older history; it does not guarantee more matching
messages. `null` means there is no next page. Do not submit the final page's null
as a next-page cursor: request `cursor=null` starts again at the newest page.

```json
{
  "channel": {
    "channel_id": "10001",
    "channel_name": "sync-events",
    "channel_protocol": "chat.v1"
  },
  "messages": [
    {
      "seq": "123",
      "uuid": "987654",
      "ts_ms": "1710000000000",
      "channel_id": "10001",
      "channel_name": "sync-events",
      "channel_protocol": "chat.v1",
      "principal": "10001",
      "recipients": ["90002"],
      "object_ids": ["70001"],
      "payload": {
        "encoding": "utf-8",
        "text": "{\"kind\":\"sync.record\"}",
        "truncated": false,
        "size_bytes": 22
      }
    }
  ],
  "next_cursor": {"before_seq": "123"}
}
```

Top-level `channel` is returned only when a `channel_id` filter is supplied,
including for empty results. That Channel's existence and read permission must be
checked by an upstream call in this request. Without Fetch, View still calls
GetChannel; cached metadata cannot substitute for authorization. Each message's
Channel name and protocol come from GetChannel, with empty values preserved.
`object_ids` preserve order and duplicates and are for viewing and correlation,
not credentials for reading objects.

### 4.3 Complete Payload

```http
POST /v1/messages/123/payload
Content-Type: application/json

{"principal":"10001","token":"tok_xxx"}
```

The path seq follows the common uint64 rules; `/v1/messages/0/payload` is valid.
The body follows the common principal and token rules. The service authenticates
and reads the target message again rather than trusting data copied from the list.

The response is `{"message": {...}}`, with the same metadata as a list message and
the complete payload representation defined below. It always has
`truncated=false`, without the list preview size limit. Missing and ACL-invisible
messages both return `404 NOT_FOUND`; `PERMISSION_DENIED` while reading the target
or its Channel metadata also maps to `404`. Invalid credentials still return
`401 UNAUTHENTICATED`.

### 4.4 Payload Representation

`payload` always includes `encoding`, `truncated`, and the original `size_bytes`.
The list inline threshold is fixed at 16384 bytes (16 KiB), with no configuration setting.

- Complete representation: decode valid UTF-8 unchanged into `text` with
  `encoding=utf-8`; otherwise return Base64 `text` with `encoding=base64`.
  The backend does not parse JSON inside payloads, return a `json` field, or
  rewrite whitespace, numbers, or duplicate keys. The HTTP response remains a
  JSON object, with payload content transported as a string.
- List payloads with `size_bytes <= 16384` use the complete representation,
  `truncated=false`, and omit `preview`.
- Larger list payloads do not construct complete text or Base64. They omit
  `text`, set `truncated=true`, and return only a head/tail preview.
- Each preview end uses at most 8192 original bytes. If the complete payload is
  valid UTF-8, boundaries shrink inward to complete characters and return text.
  Otherwise each slice is Base64-encoded separately; the two encoded strings
  cannot be concatenated and decoded together.
- `head_bytes` and `tail_bytes` are the actual original byte counts, and
  `omitted_bytes = size_bytes - head_bytes - tail_bytes`. Inapplicable fields are omitted.

```json
{
  "encoding": "utf-8",
  "truncated": true,
  "size_bytes": 20000,
  "preview": {
    "head": "...",
    "tail": "...",
    "head_bytes": 8192,
    "tail_bytes": 8192,
    "omitted_bytes": 3616
  }
}
```

The complete-content URL is constructed from the parent message seq; payload does
not repeat the seq or return a detail URL.

### 4.5 Errors

Errors use `{"error":{"code":"INVALID_ARGUMENT","message":"..."}}`.
Limit validation messages use the configured `history.max_limit` as their upper bound.
This format applies before a response starts, while the connection remains
writable. Client disconnects, response write failures, and write timeouts close
the connection; no second error response is sent after a response has started.
Request body read timeouts still return the error below.

| Condition | HTTP | code |
| --- | --- | --- |
| Invalid parameters or JSON | `400` | `INVALID_ARGUMENT` |
| HTTP request body read timeout | `408` | `REQUEST_TIMEOUT` |
| Request body too large | `413` | `REQUEST_TOO_LARGE` |
| Invalid credentials | `401` | `UNAUTHENTICATED` |
| Upstream permission denied | `403` | `PERMISSION_DENIED`; detail visibility errors return 404 under the [complete payload rules](#43-complete-payload) |
| Resource missing | `404` | `NOT_FOUND` |
| Upstream unavailable | `503` | `UNAVAILABLE` |
| Individual upstream RPC timeout | `504` | `DEADLINE_EXCEEDED` |
| Total query budget expired | `504` | `QUERY_TIMEOUT` |
| Fetch cursor does not advance | `502` | `BAD_GATEWAY` |
| Other gRPC error | `502` | Corresponding gRPC code, or `BAD_GATEWAY` without a code |
| View internal error | `500` | `INTERNAL` |
