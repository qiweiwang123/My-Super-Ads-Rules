import json
import urllib.request
from collections import defaultdict

# 上游规则的 URL 列表（您可以把想合并的加进去）
sources = [
    "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing/geo/geosite/category-ads-all.json",
    "https://raw.githubusercontent.com/KaringX/karing-ruleset/sing/geo/geosite/category-ads-all.json"
]

merged_data = defaultdict(set)

def fetch_and_parse(url):
    print(f"下载: {url}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        # 提取 rules 里的域名并去重
        for rule in data.get("rules", []):
            if "domain" in rule:
                merged_data["domain"].update(rule["domain"])
            if "domain_suffix" in rule:
                merged_data["domain_suffix"].update(rule["domain_suffix"])

for url in sources:
    try:
        fetch_and_parse(url)
    except Exception as e:
        print(f"解析失败 {url}: {e}")

# 整理成 sing-box 格式的 JSON
final_rules = [{"domain": sorted(list(merged_data["domain"]))}]
if merged_data["domain_suffix"]:
    final_rules.append({"domain_suffix": sorted(list(merged_data["domain_suffix"]))})

final_json = {
    "version": 3,
    "rules": final_rules
}

with open("merged-ads.json", 'w', encoding='utf-8') as f:
    json.dump(final_json, f, indent=2, ensure_ascii=False)

print(f"合并完成！共提取域名: {len(merged_data['domain']) + len(merged_data['domain_suffix'])} 条")
