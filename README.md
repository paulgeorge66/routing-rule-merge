# Routing Rule Merge

面向 Mihomo/Clash 的分流规则合并项目。仓库会定时拉取多个公开规则源，按用途拆分为多个 classical rule-provider 文本文件，方便在配置或订阅转换流程中引用。

本项目只整理分流规则，不包含代理节点、订阅内容或客户端配置模板。去广告规则请使用独立项目 [`paulgeorge66/adblock-rule-merge`](https://github.com/paulgeorge66/adblock-rule-merge)。

## 订阅链接

```text
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-proxy.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-direct.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-proxy.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct.list
```

以上四个文件都在千条规则以内，使用 Mihomo/Clash classical rule-provider 文本格式，每行一条规则：

```text
DOMAIN-SUFFIX,example.com
DOMAIN,api.example.com
IP-CIDR,10.0.0.0/8,no-resolve
```

`direct`/`proxy` 两个 section 是十万级规模（Loyalsoldier 的 direct.txt/proxy.txt 占大头），全部用 classical behavior 会导致 Mihomo 每次连接都线性扫描一遍，所以按规则类型拆开：

```text
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-domains.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-cidr.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-misc.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-domains.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-cidr.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-misc.list
```

`-domains.list` 给 `behavior: domain` 用（`DOMAIN-SUFFIX` 转成 `+.` 前缀），`-cidr.list` 给 `behavior: ipcidr` 用（`no-resolve` 统一放在引用处的 `RULE-SET` 参数上，不再逐条写），`-misc.list` 是剩下的 `PROCESS-NAME`/`IP-ASN`/`DOMAIN-KEYWORD`，继续用 `behavior: classical`。

需要直接放进 Clash `rules:` 时，可以引用 routing 展开片段：

```text
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/routing-expanded-rules.yaml
```

## 输出文件

```text
dist/top-proxy.list
dist/top-direct.list
dist/apple-proxy.list
dist/apple-direct.list
dist/direct-domains.list
dist/direct-cidr.list
dist/direct-misc.list
dist/proxy-domains.list
dist/proxy-cidr.list
dist/proxy-misc.list
dist/routing-expanded-rules.yaml
dist/build-report.json
```

各文件用途：

| 文件 | 建议动作 | behavior | 说明 |
| --- | --- | --- | --- |
| `top-proxy.list` | `PROXY` | classical | 需要优先代理的补充规则 |
| `top-direct.list` | `DIRECT` | classical | 需要优先直连的补充规则 |
| `apple-proxy.list` | `PROXY` | classical | Apple 媒体和相关代理规则 |
| `apple-direct.list` | `DIRECT` | classical | Apple 常规直连规则 |
| `direct-domains.list` | `DIRECT` | domain | 通用直连域名规则 |
| `direct-cidr.list` | `DIRECT` | ipcidr | 通用直连 IP-CIDR 规则(引用时加 `,no-resolve`) |
| `direct-misc.list` | `DIRECT` | classical | 通用直连里的 PROCESS-NAME 等杂项 |
| `proxy-domains.list` | `PROXY` | domain | 通用代理域名规则 |
| `proxy-cidr.list` | `PROXY` | ipcidr | 通用代理 IP-CIDR 规则(引用时加 `,no-resolve`) |
| `proxy-misc.list` | `PROXY` | classical | 通用代理里的 DOMAIN-KEYWORD/IP-ASN/PROCESS-NAME 等杂项 |

## Mihomo/Clash 引用示例

```yaml
rule-providers:
  routing-top-proxy:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-proxy.list
    path: ./ruleset/routing-top-proxy.list
    interval: 86400
  routing-top-direct:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-direct.list
    path: ./ruleset/routing-top-direct.list
    interval: 86400
  routing-apple-proxy:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-proxy.list
    path: ./ruleset/routing-apple-proxy.list
    interval: 86400
  routing-apple-direct:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct.list
    path: ./ruleset/routing-apple-direct.list
    interval: 86400
  routing-direct-domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-domains.list
    path: ./ruleset/routing-direct-domains.list
    interval: 86400
  routing-direct-cidr:
    type: http
    behavior: ipcidr
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-cidr.list
    path: ./ruleset/routing-direct-cidr.list
    interval: 86400
  routing-direct-misc:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-misc.list
    path: ./ruleset/routing-direct-misc.list
    interval: 86400
  routing-proxy-domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-domains.list
    path: ./ruleset/routing-proxy-domains.list
    interval: 86400
  routing-proxy-cidr:
    type: http
    behavior: ipcidr
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-cidr.list
    path: ./ruleset/routing-proxy-cidr.list
    interval: 86400
  routing-proxy-misc:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-misc.list
    path: ./ruleset/routing-proxy-misc.list
    interval: 86400

rules:
  - RULE-SET,routing-top-proxy,PROXY
  - RULE-SET,routing-top-direct,DIRECT
  - RULE-SET,routing-apple-proxy,PROXY
  - RULE-SET,routing-apple-direct,DIRECT
  - RULE-SET,routing-direct-domains,DIRECT
  - RULE-SET,routing-direct-cidr,DIRECT,no-resolve
  - RULE-SET,routing-direct-misc,DIRECT
  - RULE-SET,routing-proxy-domains,PROXY
  - RULE-SET,routing-proxy-cidr,PROXY,no-resolve
  - RULE-SET,routing-proxy-misc,PROXY
  - MATCH,PROXY
```

如果同时使用去广告规则（见 [`paulgeorge66/adblock-rule-merge`](https://github.com/paulgeorge66/adblock-rule-merge)），可以按自己的需求插入，注意去广告规则要放在最前面：

```yaml
rules:
  - RULE-SET,adblock-domains,REJECT
  - RULE-SET,adblock-misc,REJECT
  - RULE-SET,routing-top-proxy,PROXY
  - RULE-SET,routing-top-direct,DIRECT
  - RULE-SET,routing-apple-proxy,PROXY
  - RULE-SET,routing-apple-direct,DIRECT
  - RULE-SET,routing-direct-domains,DIRECT
  - RULE-SET,routing-direct-cidr,DIRECT,no-resolve
  - RULE-SET,routing-direct-misc,DIRECT
  - RULE-SET,routing-proxy-domains,PROXY
  - RULE-SET,routing-proxy-cidr,PROXY,no-resolve
  - RULE-SET,routing-proxy-misc,PROXY
  - MATCH,PROXY
```

## Clash 覆写脚本示例

适用于支持 JavaScript 覆写脚本的客户端。脚本会添加本项目的 rule-provider，并把分流规则插入到 `MATCH` / `FINAL` 之前。

```javascript
function main(config) {
    config["rule-providers"] = config["rule-providers"] || {};
    config.rules = config.rules || [];

    var providers = {
        "routing-top-proxy": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-proxy.list" },
        "routing-top-direct": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-direct.list" },
        "routing-apple-proxy": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-proxy.list" },
        "routing-apple-direct": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct.list" },
        "routing-direct-domains": { behavior: "domain", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-domains.list" },
        "routing-direct-cidr": { behavior: "ipcidr", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-cidr.list" },
        "routing-direct-misc": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct-misc.list" },
        "routing-proxy-domains": { behavior: "domain", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-domains.list" },
        "routing-proxy-cidr": { behavior: "ipcidr", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-cidr.list" },
        "routing-proxy-misc": { behavior: "classical", url: "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy-misc.list" },
    };

    Object.keys(providers).forEach(function (name) {
        config["rule-providers"][name] = {
            type: "http",
            behavior: providers[name].behavior,
            format: "text",
            url: providers[name].url,
            path: "./ruleset/" + name + ".list",
            interval: 86400,
        };
    });

    var rules = [
        "RULE-SET,routing-top-proxy,PROXY",
        "RULE-SET,routing-top-direct,DIRECT",
        "RULE-SET,routing-apple-proxy,PROXY",
        "RULE-SET,routing-apple-direct,DIRECT",
        "RULE-SET,routing-direct-domains,DIRECT",
        "RULE-SET,routing-direct-cidr,DIRECT,no-resolve",
        "RULE-SET,routing-direct-misc,DIRECT",
        "RULE-SET,routing-proxy-domains,PROXY",
        "RULE-SET,routing-proxy-cidr,PROXY,no-resolve",
        "RULE-SET,routing-proxy-misc,PROXY",
    ];

    var existing = config.rules.map(function (rule) {
        return String(rule).toUpperCase().trim();
    });
    var insertIndex = config.rules.findIndex(function (rule) {
        var upper = String(rule).toUpperCase();
        return upper.indexOf("MATCH") === 0 || upper.indexOf("FINAL") === 0;
    });
    if (insertIndex === -1) insertIndex = config.rules.length;

    rules.forEach(function (rule) {
        if (existing.indexOf(rule.toUpperCase()) === -1) {
            config.rules.splice(insertIndex, 0, rule);
            insertIndex++;
        }
    });

    return config;
}
```

## 规则来源

来源配置在 [sources.yaml](sources.yaml)。本项目使用公开上游规则和少量通用补充规则。

Apple 相关的路由完全交给上游（`bm7_appletv`/`bm7_appleproxy`/`bm7_applemedia`/`bm7_appstore`/`bm7_testflight`/`bm7_systemota`/`bm7_apple`/`bm7_icloud`/`loyal_apple`），不再保留任何自定义 Apple 覆盖规则。这意味着 `apple.com`、`apple-mapkit.com` 等裸域名的直连/代理判定完全由上游决定，上游数据变化会直接改变最终行为。

| 名称 | 来源网站 | 原始规则 URL |
| --- | --- | --- |
| BlackMatrix7 AppleTV | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleTV/AppleTV.yaml> |
| BlackMatrix7 AppleProxy | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleProxy/AppleProxy.yaml> |
| BlackMatrix7 AppleMedia | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleMedia/AppleMedia.yaml> |
| BlackMatrix7 AppStore | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppStore/AppStore.yaml> |
| BlackMatrix7 TestFlight | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/TestFlight/TestFlight.yaml> |
| BlackMatrix7 SystemOTA | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/SystemOTA/SystemOTA.yaml> |
| BlackMatrix7 Apple | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Apple/Apple.yaml> |
| BlackMatrix7 iCloud | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/iCloud/iCloud.yaml> |
| Loyalsoldier apple.txt | [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules)(源自 [felixonmars/dnsmasq-china-list](https://github.com/felixonmars/dnsmasq-china-list)) | <https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/apple.txt> |
| Loyalsoldier clash-rules | [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules) | <https://github.com/Loyalsoldier/clash-rules/tree/release> |
| BlackMatrix7 Telegram/OpenAI/Google/YouTube/GitHub | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash> |

请自行确认各上游项目的许可证和使用条款。

## 构建逻辑

- 拉取 [sources.yaml](sources.yaml) 中的公开规则源
- 提取 Clash/Mihomo `payload` 条目
- 提取纯域名、`+.example.com` 和 CIDR 行
- 规范化为 `DOMAIN`、`DOMAIN-SUFFIX`、`DOMAIN-KEYWORD`、`PROCESS-NAME`、`IP-ASN`、`IP-CIDR`、`IP-CIDR6`
- 移除重复规则和被前置规则覆盖的规则
- 按 section 输出多个 rule-provider 文件，并输出 routing 展开片段
- 输出构建报告和各来源解析数量

## 本地构建

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m routing_merge.builder
```

Linux/macOS：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m routing_merge.builder
```

## GitHub Actions

[.github/workflows/build.yml](.github/workflows/build.yml) 会在 push、pull request、手动触发和每日定时任务时运行。

CI 会安装依赖、运行测试、构建 `dist/*.list` 和 `dist/routing-expanded-rules.yaml`，并在生成文件变化时自动提交更新。

## 许可证

本仓库代码使用 MIT License。生成规则文件包含上游规则项目的数据，使用时请遵守对应上游项目的许可证和使用条款。
