# 生成的规则集链接

仓库：`OWNER/REPO` · 分支：`main` · 目录：`output`

## 广告与追踪（`ads-tracking`）

广告、追踪器、公共统计、国内 HTTPDNS 广告

| 线路 | 地址 |
| --- | --- |
| 原始 raw | <https://raw.githubusercontent.com/OWNER/REPO/main/output/ads-tracking.srs> |
| jsDelivr | <https://cdn.jsdelivr.net/gh/OWNER/REPO@main/output/ads-tracking.srs> |
| fastly | <https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/ads-tracking.srs> |

规则数：3 · 来源：3 个

```json
{
  "tag": "ads-tracking",
  "type": "remote",
  "format": "binary",
  "url": "https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/ads-tracking.srs",
  "download_detour": "direct",
  "update_interval": "24h"
}
```

## 广告与遥测（`ads-telemetry`）

Geosite 广告与设备遥测、诊断上报域名合集

| 线路 | 地址 |
| --- | --- |
| 原始 raw | <https://raw.githubusercontent.com/OWNER/REPO/main/output/ads-telemetry.srs> |
| jsDelivr | <https://cdn.jsdelivr.net/gh/OWNER/REPO@main/output/ads-telemetry.srs> |
| fastly | <https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/ads-telemetry.srs> |

规则数：4 · 来源：6 个

```json
{
  "tag": "ads-telemetry",
  "type": "remote",
  "format": "binary",
  "url": "https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/ads-telemetry.srs",
  "download_detour": "direct",
  "update_interval": "24h"
}
```

## 成人内容代理（`nsfw`）

合并 KaringX 多源成人内容规则，命中后走指定代理节点

| 线路 | 地址 |
| --- | --- |
| 原始 raw | <https://raw.githubusercontent.com/OWNER/REPO/main/output/nsfw.srs> |
| jsDelivr | <https://cdn.jsdelivr.net/gh/OWNER/REPO@main/output/nsfw.srs> |
| fastly | <https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/nsfw.srs> |

规则数：3 · 来源：4 个

```json
{
  "tag": "nsfw",
  "type": "remote",
  "format": "binary",
  "url": "https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/nsfw.srs",
  "download_detour": "direct",
  "update_interval": "24h"
}
```

## 代理兜底（`proxy`）

非中国地址，放在规则链靠后作为兜底代理

| 线路 | 地址 |
| --- | --- |
| 原始 raw | <https://raw.githubusercontent.com/OWNER/REPO/main/output/proxy.srs> |
| jsDelivr | <https://cdn.jsdelivr.net/gh/OWNER/REPO@main/output/proxy.srs> |
| fastly | <https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/proxy.srs> |

规则数：1 · 来源：1 个

```json
{
  "tag": "proxy",
  "type": "remote",
  "format": "binary",
  "url": "https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/proxy.srs",
  "download_detour": "direct",
  "update_interval": "24h"
}
```

## 国内直连（`direct`）

中国域名与中国 IP，命中后直连

| 线路 | 地址 |
| --- | --- |
| 原始 raw | <https://raw.githubusercontent.com/OWNER/REPO/main/output/direct.srs> |
| jsDelivr | <https://cdn.jsdelivr.net/gh/OWNER/REPO@main/output/direct.srs> |
| fastly | <https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/direct.srs> |

规则数：2 · 来源：2 个

```json
{
  "tag": "direct",
  "type": "remote",
  "format": "binary",
  "url": "https://fastly.jsdelivr.net/gh/OWNER/REPO@main/output/direct.srs",
  "download_detour": "direct",
  "update_interval": "24h"
}
```
