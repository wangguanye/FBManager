import requests
import sys

BASE = "http://127.0.0.1:8000"
errors = []

# 1. 页面路由（9个）
for path in ["/", "/accounts", "/proxies", "/windows", "/tasks", "/ads", "/sop", "/assets", "/logs"]:
    r = requests.get(f"{BASE}{path}")
    if r.status_code != 200:
        errors.append(f"PAGE {path} → {r.status_code}")
    else:
        print(f"✅ PAGE {path} → 200")

# 2. 健康度 API
for endpoint in ["/api/health/scores"]:
    r = requests.get(f"{BASE}{endpoint}")
    if r.status_code != 200:
        errors.append(f"GET {endpoint} → {r.status_code}")
    else:
        print(f"✅ GET {endpoint} → 200")

# 3. SOP API
for endpoint in ["/api/sop", "/api/sop/actions", "/api/sop/backups"]:
    r = requests.get(f"{BASE}{endpoint}")
    if r.status_code != 200:
        errors.append(f"GET {endpoint} → {r.status_code}")
    else:
        data = r.json()
        if endpoint == "/api/sop":
            days = len(data.get("days", []))
            print(f"✅ GET {endpoint} → {days} days configured")
        elif endpoint == "/api/sop/actions":
            count = len(data) if isinstance(data, list) else len(data.get("actions", []))
            print(f"✅ GET {endpoint} → {count} actions")
        else:
            print(f"✅ GET {endpoint} → 200")

# 4. 预算引擎 API
for endpoint in ["/api/ad-accounts"]:
    r = requests.get(f"{BASE}{endpoint}")
    if r.status_code != 200:
        errors.append(f"GET {endpoint} → {r.status_code}")
    else:
        print(f"✅ GET {endpoint} → 200")

# 5. CSV 导入模板下载
for endpoint in ["/api/accounts/import/template", "/api/proxies/import/template"]:
    r = requests.get(f"{BASE}{endpoint}")
    if r.status_code != 200:
        errors.append(f"GET {endpoint} → {r.status_code}")
    else:
        print(f"✅ GET {endpoint} → template downloaded")

# 6. SOP 校验
r = requests.post(f"{BASE}/api/sop/validate", json={"days": []})
if r.status_code in [200, 400, 422]:
    print(f"✅ POST /api/sop/validate → responded {r.status_code}")
else:
    errors.append(f"POST /api/sop/validate → {r.status_code}")

print("\n" + "="*50)
if errors:
    print(f"❌ {len(errors)} 个问题:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("🎉 Phase 4 全部验收通过！")
    sys.exit(0)
