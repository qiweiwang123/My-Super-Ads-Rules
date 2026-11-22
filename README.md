# SRS 自动合并：从上游链接定时生成 sing-box 规则集

这是一个可以直接放进 GitHub 仓库的项目模板：在 `config/sources.json` 里按**分组**添加公开 HTTPS 上游链接，GitHub Actions 每天拉取，**每个组各自合并**并生成 **`.srs` 二进制文件**，同时产出**三套链接**（原始 raw / jsDelivr / fastly）和可读 JSON。

典型分组：

| 分组 | 用途 | 示例输出 |
|---|---|---|
| 广告与追踪 | 拦截类 | `ads-tracking.srs` |
| 代理兜底 | 非中国地址 | `proxy.srs` |
| 国内直连 | 中国域名/IP | `direct.srs` |
| 运营商 DM | 自定义拦截 | `carrier-dm.srs` |

每组独立编译、独立输出，可以只引用其中一组，也可以全部引用。

## 相比单组旧版的变化

| 变化 | 说明 |
|---|---|
| 多分组 | `groups` 数组，每组独立合并、独立输出，互不影响 |
| 三套链接 | 自动生成 raw / jsDelivr / fastly 三种地址，写入 `links.json` 和 `links.md` |
| 同源只下一次 | 多组共用同一上游时按 URL 缓存，只下载一次 |
| 更聪明的合并 | 单字段规则做值并集去重；多字段规则整条保留，不破坏 AND 语义 |
| 命令行参数 | 新增 `--repo`、`--branch`、`--path`，Actions 里会自动读取环境变量 |
| 兼容旧配置 | 没有 `groups` 时仍按原来的 `output_name` + `sources` 构建 |

## 默认上游

配置开箱即用，含：

- MetaCubeX [`category-ads-all`](https://github.com/MetaCubeX/meta-rules-dat/blob/sing/geo/geosite/category-ads-all.json) 广告规则（JSON）
- MetaCubeX [`tracker`](https://github.com/MetaCubeX/meta-rules-dat/blob/sing/geo/geosite/tracker.json) 追踪器规则（JSON）
- KaringX [`BanAD.srs`](https://github.com/KaringX/karing-ruleset/blob/sing/ACL4SSR/BanAD.srs)（SRS）

两种输入会统一转换为 sing-box 规则源格式并合并。请注意，各规则集的覆盖范围和误拦截风险不同；更新后先检查效果，再放进日常使用的配置。项目上游说明：[MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[KaringX/karing-ruleset](https://github.com/KaringX/karing-ruleset)。

## 输出文件

自动更新完成后，`output/` 中会有：

- `<output_name>.srs`：该组合并后的 sing-box 二进制规则集，**实际使用时优先引用它**；组数等于配置里的 `groups` 数量。
- `<output_name>.json`：相同规则的可读源文件。
- `build-manifest.json`：按组分列的上游名称、来源主机、许可/署名链接、下载内容 SHA-256、规则数量和每条规则的链接。
- `links.json` / `links.md`：**每组三套链接**（raw / jsDelivr / fastly）和可直接粘贴的 sing-box `rule_set` 片段。

假设仓库是 `alice/my-rules`、分支 `main`，某一组的 `fastly` 链接形如：

```text
https://fastly.jsdelivr.net/gh/alice/my-rules@main/output/ads-tracking.srs
```

三种线路的取舍：

| 线路 | 地址形态 | 适用 |
|---|---|---|
| 原始 raw | `raw.githubusercontent.com/<repo>/<branch>/...` | 国外直连、GitHub 原生 |
| jsDelivr | `cdn.jsdelivr.net/gh/<repo>@<branch>/...` | 通用 CDN 加速 |
| **fastly** | `fastly.jsdelivr.net/gh/<repo>@<branch>/...` | **国内直连最稳**，推荐客户端使用 |

## 安装到自己的 GitHub 仓库

1. 在 GitHub 新建仓库，把本目录中的文件上传到仓库根目录。
2. 确认默认分支为 `main`（如果你用其他默认分支，下面的直链也要改成该分支名）。
3. 在仓库 **Settings → Actions → General → Workflow permissions** 允许 workflow 获得 **Read and write permissions**，使它可以提交生成文件。
4. 打开 **Actions → Build and publish merged SRS → Run workflow** 手动执行一次；也可等待每日自动更新。
5. 检查 Actions 运行结果及仓库 `output/` 中的三个输出文件。

每日计划时间是北京时间 **02:17**。首次运行前，确保上游链接可公开访问。

## 添加分组、关闭或替换上游

编辑 `config/sources.json` 的 `groups` 数组。每个组：

```json
{
  "name": "广告与追踪",
  "output_name": "ads-tracking",
  "description": "可选说明，会写进 manifest 和 links.md",
  "sources": [
    {
      "name": "我的追踪规则",
      "url": "https://example.org/rules.srs",
      "format": "auto",
      "enabled": true,
      "license_url": "https://example.org/license"
    }
  ]
}
```

- `name`：组的显示名（可以中文）。
- `output_name`：**输出文件名**，只能含字母、数字、点、下划线、连字符；不能重名。
- `enabled`：可选，默认 `true`。设为 `false` 时整组跳过（不下载、不输出，`build-manifest.json` 里记进 `skipped_groups`），适合临时停用某个分组。
- `sources`：该组的上游列表，至少一个启用的来源。
- 来源字段：`name`、`url`（公开 HTTPS）、`format`（`auto`/`json`/`srs`）、`enabled`、`license_url`、`attribution`。

**同一个上游可以出现在多个组里**，构建时只会下载一次（按 URL 缓存）。

也可调整全局的 `output_version`（1–5）、`max_download_bytes`、`timeout_seconds`，以及链接配置：

```json
"links": { "repo": "OWNER/REPO", "branch": "main", "path": "output" }
```

在 GitHub Actions 里，`repo`/`branch` 可省略：脚本会自动读取 `GITHUB_REPOSITORY` 和 `GITHUB_REF_NAME`。

**旧版单组配置仍然可用**：没有 `groups` 时，按顶层的 `output_name` + `sources` 构建一组，行为和以前一致。

> 不要把需登录、私有或带访问令牌的 URL 放进公开仓库配置；这个模板不处理身份验证。

提交配置到仓库后会自动触发构建。若你打算公开再分发合并输出，请自行确认**每个上游**对再分发、修改和署名的许可要求；`build-manifest.json` 帮助追溯来源，但不会替你授予许可。

## 在 sing-box 中引用

在配置的 `route.rule_set` 中添加远程规则集，并用路由规则指定拦截动作：

```json
{
  "route": {
    "rule_set": [
      {
        "tag": "ads-tracking",
        "type": "remote",
        "format": "binary",
        "url": "https://raw.githubusercontent.com/OWNER/REPO/main/output/ads-tracking.srs",
        "download_detour": "direct",
        "update_interval": "24h"
      }
    ],
    "rules": [
      {
        "rule_set": "ads-tracking",
        "action": "reject"
      }
    ]
  }
}
```

把 URL 中的 `OWNER/REPO` 替换成你的仓库路径。导入的只是**匹配规则**；规则是否拒绝请求由你自己的路由配置决定。具体字段请按你所用 sing-box 版本的配置文档核对。

## 合并与兼容性说明

- `.srs` 输入由官方 `sing-box rule-set decompile` 转为 JSON；JSON 输入直接解析；最后通过官方 `sing-box rule-set compile` 生成新的二进制 `.srs`。
- 合并时优先做**安全的字段并集**：只有“单字段规则”（例如 `{"domain_suffix": [...]}`）才把值合并去重；含多个字段的规则（`domain` + `domain_suffix` + `domain_regex` 这种，字段之间是 AND 关系）**整条保留**，不跨规则拆分或合并，避免改变匹配语义。
- 其余规则按 JSON 规范化后整体去重，只删完全相同的重复规则。
- 编译后会再用官方工具反编译，并验证规则条目数量；任何下载、解析、编译或校验失败都会使 workflow 失败，不会把无效结果当作成功发布。
- Workflow 固定使用 sing-box **1.14.4**，输出规则源版本默认为 **5**。如果某个上游采用该版本无法识别的格式/字段，构建会报错而不会静默丢弃。升级工具版本时应一起检查上游兼容性。
- KaringX 提醒体积超过约 3 MiB 的 `.srs` 在 Android/iOS 上可能受内存限制影响；合并后也请检查文件大小，并在目标设备实测。

## 本地运行与测试

需要 Python 3.10+ 和 sing-box 1.14.4：

```bash
python -m unittest discover -s tests -v

# 本地生成链接时显式指定仓库信息
python scripts/build.py \
  --config config/sources.json \
  --output-dir output \
  --sing-box /path/to/sing-box \
  --repo OWNER/REPO --branch main --path output \
  --expected-sing-box-version 1.14.4
```

测试只用内置测试样本和模拟网络响应，不会访问测试上游。多组、去重、链接生成都有对应测试。项目脚本代码采用 MIT 许可证；这不改变任何上游规则数据自身的许可条件。
