# openevent-view

[English version](README.md)

`openevent-view` 是 OpenEvent 历史消息查看 Web 服务，通过已安装的 SDK 读取历史和
Channel 信息，不直接访问存储。列表按最新消息在前显示，支持 Channel 和 recipient 过滤，
包括调用方可见的系统消息。小 payload 可以直接展开，大 payload 显示预览并在新标签中
查看完整内容。

## 文档

[使用参考](docs/REFERENCE_cn.md)是配置、HTTP API、payload 表示及部署边界的权威说明。
本文只保留安装、快速开始和验证入口。

## 安装与启动

需要 Python 3.10 或更新版本。运行依赖以 [pyproject.toml](pyproject.toml) 为准；SDK 至少
为 0.8.0，实际部署时使用运行 View 的 Python 环境中已安装的 SDK，仓库中的 SDK 子模块
仅供源码参考。

```bash
make install
openevent-view
```

默认监听 `127.0.0.1:8080`，连接 `127.0.0.1:9527` 的 OpenEvent 服务。在浏览器中打开
View 地址，输入 OpenEvent 凭据即可查询。该服务默认面向可信内网，部署前请阅读
[部署边界](docs/REFERENCE_cn.md#1-部署边界)。

需要配置时，将[配置示例](docs/REFERENCE_cn.md#2-配置)保存为 YAML 文件，然后运行：

```bash
openevent-view --config openevent-view.yaml
```

开发时可直接运行本仓库源码：

```bash
PYTHONPATH=src python3 -B -m openevent.view --config openevent-view.yaml
```

`--host` 和 `--port` 可覆盖监听地址。仅构建发布 wheel 使用 `make build`，产物位于
`dist/`；临时文件、缓存和日志位于 `build/`，不写入源码目录。

`make install` 只安装本次成功构建的唯一 wheel；即使版本号未变，也替换已安装的 View。
第三方依赖按包声明补齐，已满足要求的保持不变。用 `PYTHON` 选择安装环境，例如
`make install PYTHON=/opt/openevent-view/bin/python`；不支持用 `--target`、`--prefix`
或 `--root` 把安装位置改到另一个环境。

## 快速查询

脚本和页面共用只读 POST 接口，凭据放在 JSON body 中：

```http
POST /v1/messages
Content-Type: application/json

{"principal":"10001","token":"tok_xxx","cursor":null}
```

响应包含 `messages` 和 `next_cursor`。将非空游标原样传回以读取更早消息。完整字段、
边界和错误规则见[HTTP API](docs/REFERENCE_cn.md#4-http-api)。

## 验证

测试前需要在 `PYTHON` 选定的 Python 环境中安装包声明的运行依赖和 `test` 可选依赖；
`PYTHON` 默认是 `python3`。前端测试需要 Node.js 18 或更新版本。测试不自动安装 SDK，
也不从 SDK 子模块加载代码。

```bash
make test
make check-docs
```

也可分别运行 `make test-python` 和 `make test-frontend`。端到端验证使用当前成功构建的
View wheel，以及显式指定的 OpenEvent 服务端可执行文件：

```bash
make e2e OPENEVENT_SERVER_BIN=/path/to/current/build/openevent_server
```

用 `PYTHON` 选择已有虚拟环境时，依赖检查、测试和 View 进程都使用该环境的解释器与
已安装依赖，例如：

```bash
make e2e PYTHON=/opt/openevent-view/bin/python \
  OPENEVENT_SERVER_BIN=/path/to/current/build/openevent_server
```

测试仅将本次 View wheel 安装到 `build/e2e/site/` 并从该目录加载，不创建子虚拟环境，
也不替换选定环境中已安装的 View 或第三方依赖。

服务端请使用当前版本成功构建的产物。测试产生的配置、数据和日志位于 `build/e2e/`。
