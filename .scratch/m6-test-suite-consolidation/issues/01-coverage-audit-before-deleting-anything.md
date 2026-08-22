# 01 — 刪任何東西之前，先寫覆蓋盤點

**What to build:** 一份手寫、納入版控的覆蓋盤點，讓任何人都能在不重跑舊 runner 的情況下，看出舊 simulation runner 的每一個 scenario 今天由誰負責。盤點是後續刪除的**依據**，所以它必須先存在、先被讀過，才輪到刪除。

每個 scenario 歸類為三者之一：**已被具名的新測試涵蓋**（必須寫出測試名稱，且該測試當下存在並通過）、**屬於 M7**（說明為什麼不在這裡重建）、**缺口**（說明缺什麼、以及打算怎麼補）。歸類為「已涵蓋」而寫不出測試名稱的，就是缺口，不能靠語氣蒙混。

盤點還要調和一個既有矛盾：`PLAN.md` 與 `README.md` 都聲稱那個 runner 有 28 個案例，實際執行印出的是 24 passed。沒有人知道那 4 個差在哪，或者那個數字從來就沒對過。盤點必須給出答案。

文件放在量測報告所在的目錄，但**檔頭要明確標示它是手寫的、不可重跑** —— 那個目錄裡其他東西多半是 `python -m harness` 產生的，混淆會讓讀者以為它能重現。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] 盤點文件納入版控，檔頭明確標示為手寫、非產生物、不可重跑
- [x] 舊 runner 的每一個 scenario 都被逐項處理，沒有遺漏，沒有整批帶過
- [x] 每一條「已涵蓋」都寫出對應的測試名稱，且該測試在盤點寫成當下存在並通過
- [x] 每一條「屬於 M7」都寫明為什麼不在 M6 重建
- [x] 每一條「缺口」都寫明缺什麼，以及由哪張 ticket 補
- [x] 28 vs 24 的數字矛盾有明確結論，並指出錯的是哪一份文件
- [x] 盤點寫成到本 ticket 結束期間，`pytest tests/ -q -rs` 全綠且零 skip
- [x] 盤點沒有主張任何未經執行確認的覆蓋

## Comments

完成於 2026-08-20。產出 `docs/measurements/m6-coverage-audit.md`，逐項處理 24 個 check。

**28 vs 24 的答案：** 差的四個是 `T10 AutoMisty termination semantics`，一整個 scenario，
在 M1（`8a8dee8`）隨 AutoMisty 一起被移除。`b753b42` 是 28 檢查 / 10 scenario，
`8a8dee8` 之後就是 24 / 9，此後未變。**錯的是文件不是 runner**：`README.md` 三處與
`PLAN.md` 的「遷移到 pytest」那句都在描述 M1 之前的樹。兩者由 ticket 02 修正。

**盤點結果：** 12 covered（其中 5 條的新斷言比舊的更嚴，2 條是論證而非指認）、
3 條 T8 屬 M7 且不以原形式重建、5 條 T9 屬 M7 且欠一次重建、
2 條 T4 缺口（一條由 05 斷言，一條永遠只會被報告）、2 條 T5 缺口由**新增的 ticket 06** 填。

**意外發現（缺口 2）：** 套件裡每一個 `lost_user` 測試都是**還沒動就失去使用者**
（`steps == 0`）。T5 真正買到的性質是「移動之後失去目標就不再發驅動命令」，走的是設過
invalidation epoch 的另一條讀數歷史，目前**零覆蓋**。開了 ticket 06。

**兩處是推論而非指認，已在文件中標明：** T1 的「safety floor respected」是 1× 行走倍率，
而套件只在 2× 直接斷言底線；T2 從 150cm 起步，而多起點測試只涵蓋 90–130cm。兩個論證都成立，
但它們是論證。由 ticket 07 換成直接斷言。

驗證：文件中具名的 10 個測試逐一執行 → **10 passed**；`.venv/bin/python -m pytest tests/ -q -rs`
→ **272 passed、零 skip**。本 ticket 未新增或修改任何測試與產品程式碼。

---

**Review 後的更正（2026-08-20，同日）。** 兩軸 `/code-review` 在本 ticket 上找出
Standards 4 項、Spec 5 項，其中兩項是硬瑕疵，都已在後續 commit 修正：

1. **T5 的第一條檢查原本被標成 covered，是錯的。** 文件下一行自己就寫了那是不同的
   程式路徑；啟動路徑上的狀態斷言買不到移動後路徑的性質。兩條都是缺口，Tally 由
   13/3 改為 12/4。
2. **本段原本寫「具名的 11 個測試 → 11 passed」。** 實際執行的是 11 個 node id，但文件
   只具名 10 個 —— `test_bounded_step_never_crosses_the_floor_at_the_assumed_maximum`
   跑了卻沒被寫進文件。這正是本 ticket 驗收條件「盤點沒有主張任何未經執行確認的覆蓋」
   要擋的東西，出現在證明自己遵守它的那一行。

其餘更正：T4 兩條檢查的處置分開寫（一條由 05 斷言、一條依 §14.2 永遠只報告）、
T2 起始距離的外推被標為不安全（最近距離對起點非單調）並交給 ticket 07、
T9 的 verdict 與敘述對齊、噪音推導改為引用 `PLAN.md` §14.4 不再重推、
兩處 glossary 漂移（樣本 → 讀數、measurement → reading）。
