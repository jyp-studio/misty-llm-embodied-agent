# 04 — 數出方向反轉，並先證明數得到

**What to build:** 讓每一次被掃描的 approach 回報它反轉了幾次方向。

反轉是噪音的特徵失敗模式：控制器在抵達帶邊緣讀到忽遠忽近，於是前後來回燒掉步數。**它不越過 safety floor，也可能照樣回報 `arrived`** —— 現有的兩條軸（越線、收斂）對它完全是瞎的。只量已經想到的失敗模式，就會漏掉真正該問的那個；M4 #08 已經被這件事咬過一次，當時粗網格跳過超衝帶，於是把後面的碰撞當成第一個失敗回報。

**計數器必須先看過它要偵測的東西。** 構造一個必定發生反轉的情境，證明計數器數得到 —— 高 transport lag 就能逼出反轉（衝過抵達帶 → 下一筆讀數說太近 → 後退），**不需要噪音**。診斷器沒看過它要偵測的東西，就等於沒有診斷器（M4 #07 的教訓）。

本 ticket 只負責「數得出來且證明數得對」，不負責報告怎麼呈現。

**Blocked by:** 02（**不依賴 03** —— 反轉可由 transport lag 單獨逼出，兩張票可平行進行）

**Status:** resolved

- [x] 每一次被掃描的 approach 都回報方向反轉次數
- [x] 有一個**必定反轉**的情境測試，證明計數器確實數到了反轉
- [x] 該情境不依賴噪音模型，僅用既有參數即可構造
- [x] 反轉為零的情境也有測試，確認計數器不會無中生有
- [x] 新增參數後步數上限仍不被突破，終止保證未鬆動
- [x] 測試不斷言掃描的內部資料結構或迴圈次數
- [x] `pytest tests/ -q -rs` 全綠且零 skip

## Comments

完成於 2026-08-23。`ApproachOutcome` 多一個 `direction_reversals`，在 `_SimulatedWorld.drive_time`
計數（方向已經在那裡算出來了）。`misty_agent/` 未修改。

**ticket 原文的預測是錯的，這裡照原文保留並在後面註記。** 原文寫「高 transport lag 就能逼出
反轉，不需要噪音」。後半對，前半錯：在 configured 的 `max_actual_motion_multiplier=2.0` 下，
掃到 3 秒 lag 都是**零反轉**。抵達帶有 24cm 寬，步長上界本來就替 2× 行走預留 headroom，單靠
讀數過期帶不動它越過人。反轉要等到**離開校準假設**（3×、4×）才出現。

驗收條件「該情境不依賴噪音模型，僅用既有參數即可構造」仍然成立 —— `speed_error` 就是既有參數。
錯的只是 ticket 的說明文字，不是驗收條件。`test_lag_alone_does_not_make_the_controller_reverse`
把這個被推翻的預測釘成回歸測試，免得日後有人再推一次同樣的猜想。

**寫陰性對照時撞到一個更有意思的反例：反轉對行走倍率非單調。**

| 倍率 | lag 2.0s 的反轉數 | 結果 |
|---|---|---|
| 1.5× | **2** | timeout，最近 7.2cm |
| 2.0×（configured） | **0** | arrived，最近 **−9.9cm**（開過人身上） |
| 2.5× | 2 | arrived，最近 −44.9cm |

比假設的最壞情況「更溫和」的倍率不是更溫和的案例。所以陰性對照只綁在 configured 倍率上
（`test_at_the_configured_multiplier_the_controller_stays_monotone`），不寫成「假設範圍內都不
反轉」——那句話是假的。反例本身由 `test_reversal_is_not_monotone_in_the_travel_multiplier`
保存。完整記錄在 `PLAN.md` §14.8，並已寫進 ticket 05 的注意事項：**二維網格不能假設 row 之間
可以內插。**

同一張表還說明：**乾淨的反轉數不是安全結論。** 2.0× 配 2 秒 lag 是全表最糟的安全結果卻零反轉，
而且照樣回報 `arrived`。三條軸彼此獨立，這正是要分開數的理由。

**自己做了 mutation testing，並因此抓到自己的一個錯。** 第一輪三個 mutation（計數器永不遞增／
每個命令都算一次／不接進 outcome）中，第一個只紅了 1 條測試，但應該紅 2 條。追下去發現我在
改寫陰性對照時**切檔案切太多，把頭號正面測試
`test_breaking_the_calibration_assumption_makes_the_controller_reverse` 一起刪掉了**。復原後
重跑，兩個 mutation 各紅 2 條。**如果沒做 mutation testing，這個刪除會靜悄悄地過**——套件全綠、
覆蓋卻少了一條，正是 M6 #01 盤點在防的那種事。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **295 passed、零 skip**（288 → 295）。
