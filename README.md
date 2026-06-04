# Routing Rule Merge

公开分流规则合并器。项目会从多个公开上游规则源拉取数据，按当前 VPS 分流模型拆分成可用于 Mihomo/Clash 的 rule-provider 文本文件。

这个项目只做非去广告分流规则整理，不包含代理节点、私人订阅模板、服务器发布脚本、个人订阅链接或服务器自访问域名/IP。去广告规则请使用独立项目 [`paulgeorge66/adblock-rule-merge`](https://github.com/paulgeorge66/adblock-rule-merge)。

## 输出文件

默认构建会生成：

```text
dist/top-proxy.list
dist/top-direct.list
dist/apple-proxy.list
dist/apple-direct.list
dist/direct.list
dist/proxy.list
dist/build-report.json
```

持续更新的订阅链接：

```text
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-proxy.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-direct.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-proxy.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct.list
https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy.list
```

所有 `.list` 文件使用纯文本 classical rule-provider 格式，每行一条两段式规则，CIDR 规则会保留 `no-resolve`：

```text
DOMAIN-SUFFIX,example.com
DOMAIN,api.example.com
IP-CIDR,10.0.0.0/8,no-resolve
```

## 推荐引用顺序

如果同时使用本项目和去广告项目，建议在 Mihomo/Clash 配置中按下面顺序挂载。`top-*` 放在最前面，用于保留高优先级 override；去广告规则随后生效；Apple、直连、代理规则再按分流模型依次匹配。

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
  adblock:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/adblock-rule-merge/main/dist/reject.list
    path: ./ruleset/adblock.list
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
  routing-direct:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct.list
    path: ./ruleset/routing-direct.list
    interval: 86400
  routing-proxy:
    type: http
    behavior: classical
    format: text
    url: https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy.list
    path: ./ruleset/routing-proxy.list
    interval: 86400

rules:
  - RULE-SET,routing-top-proxy,PROXY
  - RULE-SET,routing-top-direct,DIRECT
  - RULE-SET,adblock,REJECT
  - RULE-SET,routing-apple-proxy,PROXY
  - RULE-SET,routing-apple-direct,DIRECT
  - RULE-SET,routing-direct,DIRECT
  - RULE-SET,routing-proxy,PROXY
  - MATCH,PROXY
```

## Clash 覆写脚本示例

如果客户端支持 JavaScript 覆写脚本，可以用下面的方式自动加入 rule-provider，并把规则插到 `MATCH` / `FINAL` 前面：

```javascript
function main(config) {
    config["rule-providers"] = config["rule-providers"] || {};
    config.rules = config.rules || [];

    var providers = {
        "routing-top-proxy": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-proxy.list",
        "routing-top-direct": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/top-direct.list",
        "adblock": "https://raw.githubusercontent.com/paulgeorge66/adblock-rule-merge/main/dist/reject.list",
        "routing-apple-proxy": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-proxy.list",
        "routing-apple-direct": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/apple-direct.list",
        "routing-direct": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/direct.list",
        "routing-proxy": "https://raw.githubusercontent.com/paulgeorge66/routing-rule-merge/main/dist/proxy.list",
    };

    Object.keys(providers).forEach(function (name) {
        config["rule-providers"][name] = {
            type: "http",
            behavior: "classical",
            format: "text",
            url: providers[name],
            path: "./ruleset/" + name + ".list",
            interval: 86400,
        };
    });

    var newRules = [
        "RULE-SET,routing-top-proxy,PROXY",
        "RULE-SET,routing-top-direct,DIRECT",
        "RULE-SET,adblock,REJECT",
        "RULE-SET,routing-apple-proxy,PROXY",
        "RULE-SET,routing-apple-direct,DIRECT",
        "RULE-SET,routing-direct,DIRECT",
        "RULE-SET,routing-proxy,PROXY",
    ];

    var upperRules = config.rules.map(function (rule) {
        return String(rule).toUpperCase().trim();
    });
    var insertIndex = config.rules.findIndex(function (rule) {
        var upper = String(rule).toUpperCase();
        return upper.indexOf("MATCH") === 0 || upper.indexOf("FINAL") === 0;
    });
    if (insertIndex === -1) insertIndex = config.rules.length;

    newRules.forEach(function (rule) {
        if (upperRules.indexOf(rule.toUpperCase()) === -1) {
            config.rules.splice(insertIndex, 0, rule);
            insertIndex++;
        }
    });

    return config;
}
```

## 规则来源

来源配置在 [sources.yaml](sources.yaml)。初始来源来自当前 VPS 分流构建模型中的非去广告公开来源，去掉了 `REJECT` 段和个人服务器 override。

| 名称 | 来源网站 | 原始规则 URL |
| --- | --- | --- |
| BlackMatrix7 AppleTV | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleTV/AppleTV.yaml> |
| BlackMatrix7 AppleProxy | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleProxy/AppleProxy.yaml> |
| BlackMatrix7 AppleMedia | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleMedia/AppleMedia.yaml> |
| BlackMatrix7 AppStore | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppStore/AppStore.yaml> |
| BlackMatrix7 TestFlight | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/TestFlight/TestFlight.yaml> |
| BlackMatrix7 SystemOTA | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/SystemOTA/SystemOTA.yaml> |
| BlackMatrix7 Apple | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Apple/Apple.yaml> |
| Loyalsoldier private/direct/applications/lancidr/cncidr/proxy/telegramcidr | [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules) | <https://github.com/Loyalsoldier/clash-rules/tree/release> |
| BlackMatrix7 Telegram/OpenAI/Google/YouTube/GitHub | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | <https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash> |

请在公开分发生成文件前自行确认各上游项目的许可证和使用条款。

## 构建逻辑

- 拉取 [sources.yaml](sources.yaml) 中配置的公开规则源
- 提取 Clash/Mihomo `payload` 条目
- 提取纯域名、`+.example.com` 和 CIDR 行
- 规范化为以下规则类型：
  - `DOMAIN`
  - `DOMAIN-SUFFIX`
  - `DOMAIN-KEYWORD`
  - `PROCESS-NAME`
  - `IP-ASN`
  - `IP-CIDR`
  - `IP-CIDR6`
- 移除完全重复的规则
- 移除已被更高优先级前置 section 覆盖的规则
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

CI 会执行：

1. 安装依赖
2. 运行测试
3. 构建 `dist/*.list`
4. 如果生成文件发生变化，自动提交更新 `dist/*.list` 和 `dist/build-report.json`

## 许可证

本仓库代码使用 MIT License。生成规则文件会包含来自上游规则项目的数据，公开分发时请遵守对应上游项目的许可证和使用条款。
