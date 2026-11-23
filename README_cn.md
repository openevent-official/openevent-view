# openevent-view

[English version](README.md)

`openevent-view` 是 OpenEvent 历史消息查看 Web 服务，通过已安装的 SDK 读取历史和
Channel 信息，不直接访问存储。列表按最新消息在前显示，支持 Channel 和 recipient 过滤，
包括调用方可见的系统消息。小 payload 可以直接展开，大 payload 显示预览并在新标签中
查看完整内容。

## 文档

[使用参考](docs/REFERENCE_cn.md)是配置、HTTP API、payload 表示及部署边界的权威说明。
本文介绍如何构建和安装 View，以及如何查询历史消息。

## 安装与启动

View 需要 Python 3.10 或更新版本，使用所在 Python 环境中已安装的 SDK。仓库中的 SDK
子模块仅供源码参考。运行依赖见 [pyproject.toml](pyproject.toml)。

在 View 仓库根目录运行以下命令。`make install` 需要与所选 Python 兼容的 pip，最低版本为 22.3。
如果使用虚拟环境，先在当前终端激活它，再在同一终端准备 SDK、安装并启动 View。
下面以已有的虚拟环境 `/opt/openevent-view` 为例。

```bash
source /opt/openevent-view/bin/activate
```

运行 `make install` 前，先在运行 View 的 Python 环境中安装 0.13.0 或更新版本的
`openevent-sdk` wheel，或为 pip 配置能提供该版本的包源。如需自行构建 wheel，
见 [SDK 构建说明](https://github.com/openevent-official/openevent-sdk/blob/fd4dd7062786129d3fa72e95e9dcf10163972ad0/README_cn.md#构建和测试)。

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

`--host` 和 `--port` 可覆盖监听地址。

## 构建命令

在 View 仓库根目录运行 Make，默认使用当前终端的 `python3`。系统 Python 和虚拟环境均可使用。
要指定运行 View 的解释器，可用 `make install PYTHON=/opt/openevent-view/bin/python`。

| 命令 | 用途 |
| --- | --- |
| `make help` | 列出可用命令。 |
| `make build` | 在 `build/` 的临时目录中隔离构建，成功后将本次 wheel 移入 `dist/` 并打印路径。 |
| `make install` | 将本次 wheel 安装到所选 Python 环境，即使版本相同也替换旧 View。pip 只补齐缺失或版本不符的运行依赖。 |
| `make clean` | 清理 View 的临时构建文件和发布包，保留开发环境、离线依赖和其他项目的包。 |

安装位置须可写。若所选 Python 允许用户安装且能导入用户目录中的包，也可以运行
`PIP_USER=1 make install`，或在 `pip.conf` 中设置 `user = true`。使用发行版管理的系统
Python 时，安装遵循 pip 和发行版的限制。若 pip 的环境变量或配置指定了 `--python` 或 `--root`，
`make install` 会在构建前报错。

### 安装到指定目录

将 View 和依赖一起装进应用发布目录时，先运行 `make build`。用与部署环境兼容的 Python
执行下面一条命令，并把示例 wheel 路径换成本次构建打印的路径。

- `python3 -B -m pip install --target ./packages dist/openevent_view-0.1.0-py3-none-any.whl` 将包安装到 `./packages/`。
- `python3 -B -m pip install --prefix /opt/myapp dist/openevent_view-0.1.0-py3-none-any.whl` 将库和脚本安装到 `/opt/myapp` 下的 `lib/` 和 `bin/`。

`PIP_TARGET`、`PIP_PREFIX` 或 `pip.conf` 中的 `target`、`prefix` 也用于这种直接调用 pip 的用法。
运行 `make install` 前应取消这些目录设置。直接安装到目录时，已有文件和依赖按 pip 的规则处理。

### 离线安装

构建和安装都使用 pip 配置的包源。`pip.conf` 的 `[global]` 可设置共用包源，
`[wheel]` 和 `[install]` 可分别配置。在 `build/wheelhouse/` 中备齐适用于目标环境的构建依赖、
运行依赖及其间接依赖后，运行以下命令。

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS=build/wheelhouse make install
```

## 快速查询

脚本和页面共用只读 POST 接口，凭据放在 JSON body 中：

```http
POST /v1/messages
Content-Type: application/json

{"principal":"10001","token":"tok_xxx","cursor":null}
```

响应包含 `messages` 和 `next_cursor`。将非空游标原样传回以读取更早消息。完整字段、
边界和错误规则见[HTTP API](docs/REFERENCE_cn.md#4-http-api)。
