# 08 — Deploy lên Render

Hướng dẫn từng bước để public service `/health` + `/recommend` ra Internet, kèm URL chia sẻ cho app team.

> **Tổng thời gian**: ~25 phút (gồm ~5-10 phút Render build).
> **Chi phí**: $0 — dùng Free tier.
> **Architecture**: data **bundle trong code** (folder `data/` committed) → service auto-load khi boot. **KHÔNG cần `/update-db`** — chỉ 2 endpoint exposed.

---

## 0. Pre-flight checklist

### ✅ FastAPI đã có sẵn

Service hiện tại đã dùng FastAPI. Không cần thêm framework nào.

### ✅ Files quan trọng để deploy

| File | Mục đích | Trạng thái |
|---|---|---|
| `app/main.py` | FastAPI entry point + startup hook auto-load cache | ✅ Có |
| `app/api/routes.py` | 2 endpoint: `/health`, `/recommend` | ✅ Có |
| `data/dishes.json` | Bundled dish data — commit vào git | ⚠️ Cần fill data thật |
| `data/ingredients.json` | Bundled ingredient data | ⚠️ Cần fill data thật |
| `data/dish_ingredients.json` | Bundled junction data | ⚠️ Cần fill data thật |
| `requirements.txt` | Dependency list | ✅ Có |
| `render.yaml` | Auto-config cho Render | ⚠️ Sẽ tạo ở Bước 2 |

### ✅ KHÔNG được commit

`.gitignore` exclude:
- `.env` (chứa secrets)
- `__pycache__/`, `.pytest_cache/`, etc.

> **Lưu ý**: trước đây `.gitignore` exclude cả `data/*.json` (vì là runtime cache backup của `/update-db`). Khi chuyển sang bundled data, **phải un-ignore** để 3 file JSON commit được vào git.

Verify bằng:
```bash
cd d:/PBL5/meal-recommender
git status
# Phải THẤY data/dishes.json, data/ingredients.json, data/dish_ingredients.json
# KHÔNG được thấy .env
```

---

## 1. Push code lên GitHub

### 1.1 Tạo repo trên GitHub

1. Vào https://github.com/new
2. Tên repo: `meal-recommender` (hoặc tùy ý)
3. Visibility: **Private** (an toàn) hoặc **Public** (nếu muốn share code)
4. KHÔNG tick "Initialize with README" (vì local đã có file)
5. Click "Create repository"

### 1.2 Init git + commit + push

```bash
cd d:/PBL5/meal-recommender

# Init nếu chưa có
git init
git branch -M main

# Stage + commit toàn bộ
git add .
git status            # ← double-check không có .env
git commit -m "Initial commit: meal-recommender service + bundled data"

# Link lên GitHub
git remote add origin https://github.com/<YOUR_USERNAME>/meal-recommender.git
git push -u origin main
```

---

## 2. Tạo `render.yaml` (auto-config)

Render đọc file này tự setup mọi thứ → đỡ phải click trên dashboard.

Tạo file [`render.yaml`](../render.yaml) ở root project:

```yaml
services:
  - type: web
    name: meal-recommender
    runtime: python
    region: singapore        # gần VN nhất, latency thấp
    plan: free
    pythonVersion: "3.11"

    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT

    envVars:
      - key: LOG_LEVEL
        value: INFO
      - key: SOLVER_TIMEOUT_SECONDS
        value: "30"
      - key: SOLVER_NUM_WORKERS
        value: "2"
      - key: NO_REPEAT_DAYS
        value: "2"
      - key: CALORIE_DELTA
        value: "100"
      - key: WEIGHT_FRIDGE
        value: "3"
      - key: WEIGHT_EXPIRY
        value: "5"
      - key: WEIGHT_DIVERSITY
        value: "2"
      - key: WEIGHT_SHOPPING_PENALTY
        value: "3"
      - key: EXPIRY_WINDOW_DAYS
        value: "7"
      - key: MAX_INGREDIENT_CLASSES
        value: "250"

    healthCheckPath: /health   # Render dùng cái này check uptime
```

Commit + push:
```bash
git add render.yaml
git commit -m "Add render.yaml for auto-deploy"
git push
```

---

## 3. Setup Render

### 3.1 Đăng ký + connect GitHub

1. Vào https://render.com/register
2. Sign up với GitHub (nhanh nhất) — authorize Render đọc repo của bạn
3. Sau khi vào dashboard, click **"New +"** → **"Web Service"**

### 3.2 Connect repo

1. Tìm repo `meal-recommender` trong list
2. Click **"Connect"**
3. Render sẽ phát hiện `render.yaml` → tự pre-fill mọi thông tin
4. Verify:
   - Name: `meal-recommender`
   - Region: Singapore
   - Branch: `main`
   - Plan: **Free**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Click **"Create Web Service"**

### 3.3 Đợi build (5-10 phút)

Bạn sẽ thấy log scroll real-time:
```
==> Cloning from https://github.com/...
==> Using Python version 3.11
==> Running build command 'pip install -r requirements.txt'
    Collecting fastapi>=0.115.0
    Collecting uvicorn[standard]>=0.32.0
    ...
    Successfully installed fastapi-0.115.0 ortools-9.11.0 ...
==> Running 'uvicorn app.main:app --host 0.0.0.0 --port $PORT'
    INFO:     Auto-loaded 75 dishes, 60 ingredients on startup    ← @startup chạy
    INFO:     Started server process [...]
    INFO:     Uvicorn running on http://0.0.0.0:10000
==> Your service is live 🎉
```

### 3.4 Lấy URL public

Trên dashboard, ngay đầu trang sẽ hiện URL dạng:
```
https://meal-recommender-xxxx.onrender.com
```

Click vào → mở `/docs` → bạn sẽ thấy Swagger UI auto-generate cho 2 endpoint.

---

## 4. Test deployment

### 4.1 Health check

```bash
curl https://meal-recommender-xxxx.onrender.com/health
```

Kỳ vọng:
```json
{
  "status": "ok",
  "cacheLoaded": true,        ← TRUE vì @startup đã load
  "timestamp": "..."
}
```

> Nếu `cacheLoaded: false` → @startup hook lỗi (data/*.json sai schema, hoặc thiếu file). Xem Render logs.

### 4.2 Gọi `/recommend` ngay

Không cần bước trung gian — service đã có data sẵn:

```bash
curl -X POST https://meal-recommender-xxxx.onrender.com/recommend \
  -H "Content-Type: application/json" \
  -d @mock_data/sample_request.json \
  | python -m json.tool
```

Kỳ vọng `status: success` + plan đầy đủ.

---

## 5. Gửi URL cho app team

### 5.1 Test mọi thứ qua Swagger UI

Mở browser:
```
https://meal-recommender-xxxx.onrender.com/docs
```

Click từng endpoint → "Try it out" → "Execute" → xem response. App dev có thể tự test mà không cần `curl` hay code.

### 5.2 Email/Slack template gửi app team

```
Hey team,

Meal Recommender API đã live ở:
  https://meal-recommender-xxxx.onrender.com

📚 Swagger docs (interactive):
  https://meal-recommender-xxxx.onrender.com/docs

🔌 2 endpoints:
  GET  /health      — check service alive + cache loaded
  POST /recommend   — gửi RecommendRequest, nhận MealPlanResponse
                      (replan: thêm field `lockedPicks` vào request)

📋 Schema spec:
  - Input/Output: docs/CLAUDE.md §3
  - Replan flow: docs/07-replan.md
  - Sample requests: mock_data/sample_request.json,
                     mock_data/sample_replan_request.json

⚠️ Notes:
  - Free tier nên app sleep sau 15 phút idle. Request đầu tiên sau sleep
    mất ~30s wake-up. Cache tự reload từ bundled data, không cần manual.
  - Data fixed (commit trong code). Update data = git push lại để Render
    auto-redeploy.

Hỏi gì ping mình.
```

---

## 6. Caveats của Render Free tier

| Vấn đề | Mức độ | Workaround |
|---|---|---|
| **App sleep sau 15p idle** | Trung bình | Cold start ~30s. Production cần plan trả phí ($7/tháng) |
| **Cache reset khi sleep** | ✅ Tự heal | @startup tự load lại từ bundled `data/` — **không cần manual** |
| **Ephemeral filesystem** | Thấp | Bundled data trong git → luôn có khi boot |
| **750h/tháng** | Thường đủ | Service không dùng → suspend |
| **Build time** ~5-10p | Thấp | Chấp nhận được, chỉ tốn lúc deploy |

> **Lưu ý**: Vì data là **bundled** trong code, cold start tự heal cache mà không cần backend hay admin call gì cả. Đây là điểm sáng của architecture đơn giản này so với mô hình `/update-db` cũ.

---

## 7. Auto-deploy on push

Mỗi lần `git push` lên branch `main`, Render auto-rebuild + redeploy. Không cần làm gì thêm.

```bash
# Sửa code → commit → push
git add .
git commit -m "feat: improve expiry weighting"
git push
# → Render detect commit → auto-build → live trong ~5 phút
```

### Khi cần update data

Workflow đơn giản: edit JSON files → commit → push.

```bash
# Edit data/dishes.json (vd thêm dish mới hoặc fix calories)
git add data/dishes.json
git commit -m "data: add 5 new dishes"
git push
# → Render auto-redeploy → service load data mới khi boot
```

---

## 8. Troubleshooting

### Build fail ở `pip install`

→ Kiểm tra `requirements.txt` có đúng version constraint không.
→ Nhìn log Render: nếu `ortools` fail (~hay xảy ra trên Linux ARM) thì specify version cụ thể: `ortools==9.11.4210`.

### `502 Bad Gateway` khi mở URL

→ App crash khi start. Xem **"Logs"** tab trên Render dashboard để biết lỗi.
→ Common: thiếu env var, hoặc port config sai.

### `cacheLoaded: false` trên `/health`

→ @startup hook fail. Xem logs:
- File `data/dishes.json` thiếu hoặc không commit?
- JSON schema sai (vd thiếu field `calories`)?
- Cross-ref validation fail (dishId trong junction không tồn tại)?

→ Test local trước khi deploy: `python scripts/demo.py` phải pass.

### `503 Service Unavailable` khi gọi `/recommend`

→ Cache chưa load (xem trên). Service không tự retry — cần fix data + redeploy.

### Solver timeout (`status: "failed"`)

→ Pool quá nhỏ + macro strict. Tăng `SOLVER_TIMEOUT_SECONDS=60` trong env vars.

### App ngủ — request đầu tiên rất chậm

→ Bình thường với free tier. Acceptable cho demo.
→ Nếu khó chịu: dùng cron-job miễn phí (vd https://cron-job.org/) ping `/health` mỗi 14 phút.

---

## 9. Checklist tổng

Trước khi gửi URL cho app team, verify:

- [ ] `data/dishes.json`, `data/ingredients.json`, `data/dish_ingredients.json` đã có data thật + commit vào git
- [ ] `git push` đã thành công, repo có code + data mới nhất
- [ ] Render dashboard show service trạng thái **"Live"** (xanh)
- [ ] `curl https://.../health` trả 200 OK + `cacheLoaded: true`
- [ ] `curl POST /recommend` với `mock_data/sample_request.json` trả `status: success`
- [ ] Mở `https://.../docs` thấy Swagger UI với 2 endpoint (`/health`, `/recommend`)

✅ Đủ checklist → gửi URL + 1 dòng intro cho app team là xong.

---

## Tóm tắt architecture đơn giản hóa

```
[git repo]
   ├── app/                       ← code service
   ├── data/                      ← bundled JSON, commit vào git
   │   ├── dishes.json
   │   ├── ingredients.json
   │   └── dish_ingredients.json
   └── render.yaml
        │
        │ git push
        ▼
   [Render]
        │ build + deploy
        ▼
   Service boot
        │ @app.on_event("startup")
        ▼
   Đọc data/*.json → populate cache
        │
        ▼
   Service ready, /recommend hoạt động ngay
        │
        │ App gọi /recommend
        ▼
   Trả MealPlanResponse
```

**Không có**: `/update-db`, URL fetching, manual admin trigger, cron warmup.
**Có**: 2 endpoint duy nhất, data trong git, auto-redeploy khi push.
