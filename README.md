# Routing Rule Merge

面向 Mihomo 的公开分流规则。项目仅发布规则，不包含节点或真实订阅凭据；去广告由 [adblock-rule-merge](https://github.com/paulgeorge66/adblock-rule-merge) 提供。

## 规则顺序与来源

`top-proxy → top-direct → apple-proxy → apple-direct → direct → proxy → MATCH`。具体来源与所属 section 见 [sources.yaml](sources.yaml)。先匹配的规则生效；配合去广告时，REJECT 放在这些分流规则之前。

Apple 使用 BlackMatrix7 `Apple_Classical.yaml` 完整源。上游普通 `Apple.yaml` 与 `Apple_Domain.yaml` 是有意拆分，单独普通文件不是完整域名集合。AppleTV/AppleProxy/AppleMedia 的代理规则仍先于 Apple 直连规则；不另加手写 Apple 覆盖。

已移除被完整 Apple 源覆盖的 AppStore、TestFlight、SystemOTA、iCloud 与 Loyalsoldier Apple 下载来源。YouTube 与 GitHub 的域名已被总集覆盖，仅有贡献的关键词显式保存在本地规则中。远程来源共 17 个。

OpenAI 和 GitHub Copilot 使用 MetaCubeX 的完整 Classical 服务规则，微软 Copilot 的专用域名同样位于 `top-proxy`，先于 Microsoft 总集。保留 OpenAI 动态 WebPubSub 的正则匹配，避免 Azure 资源被厂商总集提前直连；其他微软服务与国内 AI 的原有策略继续生效。

Telegram 的 IP 使用官方 CIDR；BlackMatrix7 Telegram 仅提供域名、关键词与进程规则，过滤其 IP/ASN 部分。当前输出无 IP-ASN，不依赖 ASN 数据库。applications 仍采用现有进程直连策略，涵盖代理软件防环路和下载客户端；需要修改下载器策略时，可调整该来源。

不同类型的同名规则分别保留，例如 `DOMAIN-KEYWORD,onedrive` 与 `PROCESS-NAME,OneDrive`。仅删除相同类型、值的重复项，以及被前置规则或同动作父域后缀完整覆盖的规则。

domain payload 的普通域名保留为 DOMAIN 精确匹配，`+.` 才转为 DOMAIN-SUFFIX。正则表达式的大小写和转义保持原样，不与不同语义的表达式合并。

## 公开输出

基础 URL：`https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/`

| 文件 | 动作 | behavior / format |
| --- | --- | --- |
| `top-proxy.list` | PROXY | classical / text |
| `top-direct.list` | DIRECT | classical / text |
| `apple-proxy.list` | PROXY | classical / text |
| `apple-direct-domains.mrs` | DIRECT | domain / mrs |
| `apple-direct-cidr.mrs` | DIRECT | ipcidr / mrs |
| `apple-direct-misc.list` | DIRECT | classical / text |
| `direct-domains.mrs`、`direct-cidr.mrs`、`direct-misc.list` | DIRECT | domain、ipcidr、classical |
| `proxy-domains.mrs`、`proxy-cidr.mrs`、`proxy-misc.list` | PROXY | domain、ipcidr、classical |

每个 MRS 都有对应 `.list` 文本。`apple-direct.list` 保留完整 classical 文件供旧配置兼容；新配置推荐拆分后的 MRS，减少域名解析和匹配成本。

- `routing-expanded-rules.yaml`：带两个空格列表缩进，末尾有且仅有 `MATCH,PROXY`，供历史消费者使用。
- `routing-expanded-fragment.yaml`：相同路由内容，不包含 MATCH，供 Worker 流式拼接。
- `proxy-dns-domains.yaml`：代理 section 的域名/域名后缀，六个空格列表缩进，供展开模式的 `dns.fallback-filter.domain` 使用。不含 PROCESS-NAME、IP、关键词规则。
- `manifest.json`、`build-report.json`：文件完整性、源状态、剪枝与构建校验结果。
- `adblock-overlap.csv/json`：与已验证去广告快照的覆盖诊断，包含手写优先规则冲突。诊断不添加放行例外；不可用时 JSON 明确标记 unavailable。

## 配置示例

```yaml
rule-providers:
  routing-apple-direct-domains:
    type: http
    behavior: domain
    format: mrs
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct-domains.mrs
    path: ./ruleset/apple-direct-domains.mrs
    interval: 21600
    size-limit: 500000
  routing-apple-direct-cidr:
    type: http
    behavior: ipcidr
    format: mrs
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct-cidr.mrs
    path: ./ruleset/apple-direct-cidr.mrs
    interval: 21600
rules:
  # 完整配置还需按上述顺序引用其他 provider。
  - RULE-SET,routing-apple-direct-domains,DIRECT
  - RULE-SET,routing-apple-direct-cidr,DIRECT,no-resolve
  - MATCH,PROXY
```

IP-CIDR provider 引用加 `no-resolve`，与原始路由语义一致。完整可恢复配置生成器在私有运维手册中；本仓库的示例不包含节点。

## 构建与发布保障

GitHub Actions 在 push、PR、手动触发和每天三次（间隔八小时）的定时任务中运行。定时任务可能被 GitHub 延迟；它不是准点更新保证。

- 按声明的 domain/classical/ipcidr payload 格式解析，检查域名、CIDR 地址族、最低/最高条目数、异常跌幅和增长、关键类型。
- 最多四个源并行下载，按配置顺序合并，避免网络完成顺序影响优先级。
- 同一个 GitHub 仓库及分支先解析一个 SHA，再从该固定版本下载全部文件。整组格式、数量和关键规则通过后才替换快照；任何文件失败时整组回退到 24 小时内的已验证版本，避免新旧文件混用。SHA 未变化时复用校验过的文件。版本和正文哈希写入构建报告。
- 使用 ETag/Last-Modified 条件请求；只有成功解析、校验的快照才写入 `.cache/sources`。上游异常时最多使用 24 小时内的同 URL 已验证快照，报告标记 `stale`；没有合格快照就停止发布。
- 发布前执行来源配置中的 21 个域名去向检查，覆盖 OpenAI Azure 资源、Copilot、动态 WebPubSub、国内 AI、Microsoft、Apple 和精确域名的子域行为。策略回归会停止发布。
- 发布前检查每个文件的消费者大小上限、LF、重复条目、展开片段和最终 MATCH；对 MRS 做反向转换并核对匹配范围，再运行 Mihomo 配置检查。
- Mihomo 固定 v1.19.29，下载校验 SHA-256。所有检查成功后才写 `manifest.json` 并提交整套产物。manifest 记录文件字节数、SHA-256、条目数和是否降级。

本地先安装 `requirements.txt`，运行 `python -m unittest discover -v`，再执行构建器。MRS 转换和发布验证命令见 [.github/workflows/build.yml](.github/workflows/build.yml)。构建器产出的文本是中间结果；消费者应使用已通过完整 CI 的 `dist`。

本地文本构建：`python -m routing_merge.builder`。

## 许可证

代码使用 MIT License；生成规则包含上游数据，请遵守对应上游的许可证与使用条款。
