# 09 — Unit Conversion: NUMBER ↔ GAM

> **Status**: spec/proposal — chưa code. Đọc xong, bạn confirm thì mình implement.

---

## Vấn đề bạn đang gặp

### Vấn đề 1 — Fridge gửi NUMBER, service không xử được

App scan tủ lạnh xong, có thể gửi:

```json
"fridge": [
  { "ingredientId": 2, "quantity": 5, "unit": "NUMBER", "dueDate": "..." }
  // 5 quả trứng vịt
]
```

Service cần convert `5 quả` → grams (để track stock chung với các ingredient khác đo bằng GAM).

→ Cần biết **1 quả trứng vịt nặng bao nhiêu gam**?

Hiện tại service tra `Ingredient.numberToGam`. Nhưng `ingredient_full.csv` của bạn **không có cột này**.

→ Lỗi `InvalidIngredientError`. App phải tự convert sang GAM trước → bất tiện.

### Vấn đề 2 — Cá dìa mismatch

Bạn đang phân vân:

```csv
ingredient_full.csv:
26,Cá dìa,...,GAM,...      ← unit=GAM (bán theo cân ở chợ)

DishIngredient_rows.csv:
161,27,26,1,100,NUMBER     ← dish 27 dùng "1 con cá dìa", unit=NUMBER
```

Câu hỏi: nên đổi ingredient_full thành NUMBER, hay đổi DishIngredient thành GAM?

---

## Insight quan trọng

Hai field unit này có **ý nghĩa khác nhau**, không cần khớp:

| Field | Ý nghĩa | Ví dụ cá dìa |
|---|---|---|
| `ingredient_full.unit` | Đơn vị **display/storage** mặc định (cách user mua/đo ở chợ) | `GAM` — bán theo cân |
| `DishIngredient.unit` | Đơn vị **của recipe cụ thể đó** | `NUMBER` — "1 con cá dìa" tự nhiên hơn cho công thức |

→ Recipe có quyền dùng đơn vị tự nhiên cho từng dish. Service không cần ép consistency.

→ **Bạn không phải đánh lại data**. Cứ giữ như đang có.

Với điều kiện: `DishIngredient.gramsEqui` luôn được fill chính xác (= trọng lượng thật của amount đó). Ví dụ:

```
161,27,26,1,100,NUMBER     ← 1 con cá dìa, gramsEqui=100 (1 con = 100g)  ← OK
```

Service tin tưởng `gramsEqui` để tính nutrition + track stock. `unit` chỉ để output user-friendly.

---

## Đề xuất cách giải quyết — derive `numberToGam` từ junction table

### Ý tưởng

Lúc service load data ở `/update-db`, **tự build 1 map** từ DishIngredient junction rows:

```
{ingredient_id: gam_per_unit_NUMBER}
```

Sau đó **dùng map này khi fridge gửi NUMBER**.

### Cách derive map

Walk qua mọi row trong DishIngredient:
- Nếu `unit=NUMBER` và `amount > 0` và `gramsEqui có giá trị`
- Lưu sample: `gam_per_unit = gramsEqui / amount`
- Sau khi quét hết, average các sample của cùng ingredient

```python
def derive_number_to_gam(rows):
    samples = defaultdict(list)
    for row in rows:
        if row.unit == "NUMBER" and row.amount > 0 and row.gramsEqui:
            ratio = row.gramsEqui / row.amount   # gam mỗi 1 unit
            samples[row.ingredientId].append(ratio)

    return {
        ing_id: sum(s) / len(s)   # trung bình
        for ing_id, s in samples.items()
    }
```

### Áp dụng vào data thật của bạn

Với các row NUMBER hiện có trong DishIngredient_rows.csv:

```
3,1,6,1,150,NUMBER       → 1 củ hành tây = 150g
21,4,2,1,70,NUMBER       → 1 quả trứng vịt = 70g
13,5,68,3,36,NUMBER      → 3 quả trứng cút = 36g (tức 12g/quả)
26,6,12,1,55,NUMBER      → 1 quả trứng gà = 55g
161,27,26,1,100,NUMBER   → 1 con cá dìa = 100g
46,7,12,1,55,NUMBER      → 1 quả trứng gà = 55g (lại)
```

Service tự build map:

```python
{
  2: 70.0,    # trứng vịt
  6: 150.0,   # hành tây
  12: 55.0,   # trứng gà (xuất hiện nhiều lần, average vẫn 55)
  26: 100.0,  # cá dìa
  68: 12.0,   # trứng cút
  ...
}
```

### Cách dùng map

Khi fridge gửi `5 quả trứng vịt`:

```python
# unit_converter.to_gam (sửa lại)
def to_gam(quantity, unit, ingredient_id, snapshot):
    if unit == GAM:
        return quantity

    # NUMBER: tra map đã derive
    factor = snapshot.derived_number_to_gam.get(ingredient_id)
    if factor is None:
        # Fallback: thử ingredient.numberToGam (legacy)
        factor = ingredient.number_to_gam
    if factor is None:
        raise InvalidIngredientError(
            f"Ingredient {ingredient_id} không tìm được conversion NUMBER→GAM. "
            f"Cần ít nhất 1 row trong DishIngredient junction với unit=NUMBER."
        )
    return quantity * factor
```

→ Fridge `5 quả trứng vịt` → tra map → `5 × 70 = 350g` → track stock OK.

---

## Edge cases

| Tình huống | Hành xử |
|---|---|
| Ingredient X chưa từng có row NUMBER trong junction | `derived[X]` không có. Fallback `ingredient.numberToGam` (nếu có). Nếu cả 2 không có và fridge gửi NUMBER → `InvalidIngredientError` (400) |
| Junction có 2 row khác giá trị (vd "1 quả = 60g" vs "1 quả = 70g") | Average → 65g. Đủ chính xác cho mục đích planning |
| Cá dìa có 3 dish dùng với gramsEqui khác nhau (1 con = 100g, 200g, 300g) | Average → 200g. Chấp nhận sai số vì cá dìa thật cũng đa dạng kích cỡ |
| User mới crawl 1 dish cho ingredient mới, gramsEqui chưa fill | `derived` không có entry. Fallback hoạt động hoặc raise lỗi rõ ràng |
| Fridge gửi GAM cho ingredient có unit=NUMBER trong master | Pass thẳng, không tra map (chỉ NUMBER → GAM mới cần tra) |

---

## So sánh 2 approach

| | Cách cũ (`ingredient.numberToGam`) | Cách mới (derive từ junction) |
|---|---|---|
| Backend phải thêm cột mới? | ❌ Có | ✅ Không |
| User fill thủ công? | ❌ Có (cho mọi ingredient unit=NUMBER) | ✅ Không — auto từ junction đã có |
| Cập nhật khi data đổi? | Phải edit DB rồi re-export | ✅ Tự động khi /update-db |
| Linh hoạt với "1 quả=60 hôm nay, 70 hôm khác" | ❌ Một giá trị cố định | ✅ Auto average |
| Cá dìa NUMBER/GAM mismatch issue | ⚠️ Phải force consistency | ✅ Không cần consistent |
| Effort | User work | Service code ~30 phút |

---

## Implementation outline

### Files thay đổi

| File | Thay đổi |
|---|---|
| `app/core/cache.py` | `DBSnapshot` thêm field `derived_number_to_gam: dict[int, float]` |
| `app/services/db_loader.py` | Thêm hàm `_derive_number_to_gam(rows)`, gọi trong `load_from_urls`, attach vào snapshot |
| `app/services/unit_converter.py` | `to_gam` accept thêm tham số `derived_map`, ưu tiên dùng map này trước fallback `ingredient.number_to_gam` |
| `app/services/missing_ingredient.py` | Pass `snapshot.derived_number_to_gam` vào `to_gam` |
| Tests | Thêm test cho derive logic + fridge NUMBER conversion |

### Estimated effort

- 30 phút code
- 15 phút test
- Total: ~45 phút

### Backward compat

- `ingredient.numberToGam` vẫn fallback nếu derive không cover → không phá data cũ
- Test cũ pass nguyên vẹn (chưa có data NUMBER fridge → branch mới không trigger)

---

## Câu hỏi cho bạn

1. **OK với approach này?** (derive từ junction, không thêm cột)
2. **Có muốn mình code không?** (~45 phút)
3. **Hoặc bạn muốn alternative khác?** (vd: bắt buộc app convert NUMBER→GAM ở client side)

---

## TL;DR

- **Cá dìa NUMBER/GAM mismatch**: KHÔNG phải vấn đề, không cần đánh lại data. 2 field có ý nghĩa khác nhau.
- **Fridge gửi NUMBER**: service tự derive `numberToGam` từ DishIngredient junction → không cần app convert, không cần thêm cột.
- **Lợi**: 0 thay đổi data, 0 thay đổi backend, chỉ ~45' code service.
