# OpenEvent View 使用参考

[English version](REFERENCE.md)

本文是 View 的配置、HTTP API 和部署边界的唯一权威说明。安装和启动见
[README](../README_cn.md)；上游历史、认证和权限语义见
[OpenEvent API](../openevent-sdk/docs/API_cn.md)。View 是只读查看工具，通过部署时运行
View 的 Python 环境中已安装的 `openevent-sdk>=0.8.0` 访问 OpenEvent，不直接读取服务端存储。

## 1. 部署边界

View 面向可信内网，默认监听本机。查询权限由请求中的 OpenEvent `principal/token`
决定，没有管理员身份代查、消息发布或 Channel 修改接口。部署到其他网络时，由部署方提供
适合该环境的访问控制、TLS、流量管理和日志策略；View 不自带这些网关能力。

两个消息接口只接受 JSON body 中的凭据，不使用 URL、认证 header、cookie 或服务端 session。
凭据不写入日志或浏览器存储。页面可以在内存中保存当前生效查询的凭据，替换查询状态或关闭
页面后释放引用。详情页在新标签中打开，通过同源窗口内存消息接收凭据；直接打开、交接失败
或超过 5 秒时，需要重新输入凭据。新标签被拦截时，列表保留原状并提示允许弹窗后重试。

View 不跨请求缓存消息或 payload，只保留有界的 Channel 展示信息缓存。消息接口的成功和
错误响应均使用 `Cache-Control: no-store`。SDK `object_keys` 只投影为保持顺序和重复项的
`object_ids`；`object_token` 不进入 HTTP 响应、HTML、页面状态或日志。此规则不解释或修改
不透明 payload 中的内容。

## 2. 配置

省略配置文件或省略字段时使用以下默认值：

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

| 字段 | 说明与范围 |
| --- | --- |
| `version` | 必须为 `v1` |
| `server.host` | 非空的 HTTP 监听地址 |
| `server.port` | HTTP 端口，整数 `1..65535` |
| `server.request_timeout_seconds` | HTTP socket 读写超时，有限正数，单位为秒 |
| `server.query_timeout_seconds` | 一次历史或详情查询的总预算，有限正数，单位为秒；涵盖认证、Fetch、扫描、消息投影以及 Channel 查询和排队 |
| `server.max_request_body_bytes` | POST 请求体字节数上限，正整数 |
| `openevent.target` | 非空的 OpenEvent gRPC 地址 |
| `openevent.rpc_timeout_seconds` | 单次 OpenEvent RPC 的最大等待时间，有限正数，单位为秒；同时受查询剩余预算限制 |
| `openevent.channel_cache_size` | Channel 展示信息 LRU 缓存的最大条目数，正整数 |
| `openevent.channel_lookup_workers` | Channel 查询的全局最大并发数，整数 `1..64` |
| `history.default_limit` | API 默认返回条数，整数 `1..history.max_limit` |
| `history.max_limit` | API 允许的最大返回条数，整数 `1..1000` |
| `history.fetch_batch_size` | 固定扫描窗口的 seq 跨度及单次 `Fetch.limit`，整数 `1..1000` |

整数和数值配置都不接受 boolean。配置必须满足
`1 <= history.default_limit <= history.max_limit <= 1000`；不合法时拒绝启动。
`history.max_limit` 可以大于 `history.fetch_batch_size`，一页会扫描多个窗口。
过滤后消息稀疏时也使用同样大小的窗口，直到凑满一页、到达历史下界或查询预算耗尽。

HTTP socket 超时、单次 RPC 超时和整次查询预算是三个不同限制。查询预算在 RPC、扫描、
消息投影和 Channel 等待边界检查，不会强行中断正在执行的单次 CPU 转换。预算耗尽返回
`504 QUERY_TIMEOUT`，不返回未完成的半页结果。内置浏览器页面另有固定 35 秒请求上限；
提高服务端预算不会提高浏览器上限，使用更长预算的脚本需设置自己的 HTTP 超时。

## 3. 页面

`GET /` 返回历史列表；`GET /message?seq=123` 返回完整 payload 页面。详情 URL 只包含
规范十进制 `seq`，包括合法的 `seq=0`，不包含凭据。

列表按 seq 从大到小显示，支持 Channel 和 recipient 过滤，也显示调用方可见的系统消息。
页面使用服务端默认页大小，不暴露 `from_seq`、`limit` 或游标输入框。“下一页”查看更早消息，
“上一页”重新查询已访问的较新页，“查看最新”重新读取最新页。重新查询的结果可能随新增
消息或权限变化而改变，页面不会自动插入新消息。

修改输入框不会改变已显示结果的查询条件；只有“查询”成功才切换生效状态。分页、查看最新
和打开完整内容使用当前结果的凭据及条件。每次请求等待期间保留原结果，成功后一次性替换；
失败或超时后保留原结果和分页位置、显示原因并恢复操作。页面同时只执行一个操作，
请求在 35 秒后自动取消等待；关闭页面也可放弃等待。浏览器停止等待不保证服务端
立即停止工作，服务端仍由自己的查询预算限制。

每条消息显示顶层元数据和 payload，并标明 payload 编码和原始字节数，包括列表预览。
完整 UTF-8 文本由浏览器尝试按 JSON 渲染；解析成功时默认显示树，可切换查看原文，失败时
直接显示原文。JSON 的对象、数组按需展开，每批显示 100 个直接子项，其余通过“显示更多”
继续查看。JSON 树遵循 JavaScript 数字规则，可能无法精确表示大整数，核对内容以原文为准。
大 payload 在列表中显示预览，通过新标签查看完整内容。外部字段和错误信息只作为文本
或 JSON 节点展示，不作为 HTML 或脚本执行。

## 4. HTTP API

### 4.1 通用规则

请求为带 `Content-Length` 的 POST JSON object，使用 `orjson.loads` 解析。无效 JSON 或
顶层不是 object 时返回 `400 INVALID_ARGUMENT`。不提供带鉴权的 GET 变体。

所有 OpenEvent uint64 值（ID、seq、时间戳、recipients、游标）使用规范十进制字符串：
`"0"` 或不以零开头的数字串，最大 `"18446744073709551615"`；不允许符号、空格或前导零。
请求调用方 `principal` 必须大于 0；`channel_id`、详情 `seq` 和 `cursor.before_seq` 可以为 0。
`limit`、payload 字节数等有界计数使用 JSON number。本规则不改变不透明 payload 自身的数字表示。

每次历史和详情查询都先用本次 `principal/token` 调用 `GetStatus`。即使游标已到历史边界，
无效凭据仍返回 `401`。`min_seq=0` 是有效初始化状态，`max_seq=0` 表示只有初始化消息，
不表示历史为空。View 可显示 seq 0 和 Channel 0 中的消息，其可见性仍由 OpenEvent 决定。

### 4.2 查询历史

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

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `principal` | 是 | 正 uint64 十进制字符串，查询身份 |
| `token` | 是 | 非空字符串，查询凭据 |
| `cursor` | 否 | 省略或 `null` 读取最新页；否则为只包含 `before_seq` 的 object |
| `limit` | 否 | 整数 `1..history.max_limit`，boolean 非法；省略使用 `history.default_limit` |
| `channel_id` | 否 | uint64 十进制字符串；省略或 `null` 表示不过滤 Channel |
| `only_my_recipient` | 否 | boolean，默认 `false`，传给 OpenEvent Fetch |

唯一非空游标格式为 `{"before_seq":"123"}`，表示只读取 `seq < 123`。
缺少字段或含额外字段的游标非法。`{"before_seq":"0"}` 合法，认证成功后返回空页。
游标只记录位置，不绑定凭据、过滤条件或页大小；每次请求使用本次参数。
Channel 与 recipient 过滤同时提供时必须同时满足。

响应中的 `messages` 按 seq 倒序排列。`next_cursor` 非空时，原样传回以继续读取更早历史，
它不保证更早位置一定还有匹配消息；为 `null` 时没有下一页。不能把末页的 `null` 当作
下一页参数发送，因为请求中的 `cursor=null` 表示重新查询最新页。

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

只有请求指定 `channel_id` 时才返回顶层 `channel`，即使结果为空也返回。该 Channel 的存在性
和读取权限必须通过本次上游调用检查；没有进行 Fetch 时仍会调用 GetChannel，不能用旧缓存
代替授权。每条消息的 Channel 名称和 protocol 来自 GetChannel；空值原样返回。
`object_ids` 保持原顺序和重复项，仅用于查看、关联，不能作为对象读取凭据。

### 4.3 完整 payload

```http
POST /v1/messages/123/payload
Content-Type: application/json

{"principal":"10001","token":"tok_xxx"}
```

路径 seq 遵守通用 uint64 规则，`/v1/messages/0/payload` 合法。body 使用通用的 principal
和 token 规则。服务重新认证并读取目标消息，不信任列表页复制的数据。

响应为 `{"message": {...}}`，message 元数据与列表相同，payload 按下一节完整表示，
始终 `truncated=false`，不受列表预览阈值限制。不存在和 ACL 不可见统一返回 `404 NOT_FOUND`；
读取目标消息或其 Channel 信息时的 `PERMISSION_DENIED` 也映射为 `404`。
无效凭据仍返回 `401 UNAUTHENTICATED`。

### 4.4 Payload 表示

`payload` 始终有 `encoding`、`truncated` 和原始 `size_bytes`。列表内联阈值固定为
16384 字节（16 KiB），不提供配置项。

- 完整表示：有效 UTF-8 原样解码到 `text`，`encoding=utf-8`；非 UTF-8 编码为 Base64
  `text`，`encoding=base64`。后端不解析 payload 内的 JSON，不返回 `json` 字段，也不改写
  其中的空白、数字或重复键。HTTP 响应仍是 JSON 对象，payload 内容作为字符串传输。
- 列表中 `size_bytes <= 16384` 使用完整表示、`truncated=false`，省略 `preview`。
- 列表中 `size_bytes > 16384` 不构造完整文本或 Base64；省略 `text`，设置
  `truncated=true`，只返回头尾预览。
- 预览各取至多 8192 个原始字节。完整 payload 是有效 UTF-8 时，头尾向内调整到完整字符
  边界，并返回文本；否则两个切片分别编码为 Base64，不能把两段编码拼接后解码。
- `head_bytes`、`tail_bytes` 是实际使用的原始字节数，
  `omitted_bytes = size_bytes - head_bytes - tail_bytes`。不适用的字段直接省略。

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

完整内容入口从父消息 seq 构造，payload 不重复返回 seq 或详情地址。

### 4.5 错误

错误统一为 `{"error":{"code":"INVALID_ARGUMENT","message":"..."}}`。
limit 校验错误中的上限使用当前配置的 `history.max_limit`。
此格式适用于响应尚未开始、连接仍可写的情况。客户端断开、响应写入失败或写入超时
时关闭连接；响应开始后不再补发另一份错误响应。请求体读取超时仍按下表返回错误。

| 场景 | HTTP | code |
| --- | --- | --- |
| 请求参数或 JSON 非法 | `400` | `INVALID_ARGUMENT` |
| HTTP 请求体读取超时 | `408` | `REQUEST_TIMEOUT` |
| 请求体过大 | `413` | `REQUEST_TOO_LARGE` |
| 凭据无效 | `401` | `UNAUTHENTICATED` |
| 上游拒绝权限 | `403` | `PERMISSION_DENIED`，详情可见性错误按[完整 payload 接口规则](#43-完整-payload)返回 404 |
| 资源不存在 | `404` | `NOT_FOUND` |
| 上游不可用 | `503` | `UNAVAILABLE` |
| 单次上游 RPC 超时 | `504` | `DEADLINE_EXCEEDED` |
| 整次查询预算耗尽 | `504` | `QUERY_TIMEOUT` |
| Fetch 游标不前进 | `502` | `BAD_GATEWAY` |
| 其他 gRPC 错误 | `502` | 对应 gRPC code，无 code 时为 `BAD_GATEWAY` |
| View 内部错误 | `500` | `INTERNAL` |
