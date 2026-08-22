# 03 — 距離相依的噪音模型，並證明它與真實偵測器一致

**What to build:** 讓 Sweep 能問「偵測抖動多大時控制器開始失效」，而且問的方式與生產管線的誤差結構一致。

**參數是像素抖動，不是公分。** 距離由 pinhole 關係從臉的像素寬推得，距離與像素寬成反比，所以固定的像素抖動造成的公分誤差隨**距離平方**放大。在預設校正常數下，safety floor 附近 1px 只有約 0.2cm，200cm 處是約 4.1cm。舊 runner 用的與距離無關的均勻公分噪音因此在**決定安全的近距離注入了物理上不可能的誤差**（相當於臉寬的 17%），在**偵測真正不穩的遠距離又注入得不夠** —— 兩邊都錯，而且錯的方向剛好讓安全結論失真。誤差套用後仍要走管線既有的整數截斷；模型不得比生產管線精確。

噪音從 **Sweep 現有的感知注入點**進入，也就是 transport lag 目前進去的同一個地方。不新增第二條注入路徑。`approach()`、控制律與正式距離管線在本 ticket **一行不改**。

抖動幅度明列為 **UNCALIBRATED**，與 sensor transport lag 同級：從未被量過，沒有硬體也量不到。任何敘述都不得暗示它是量出來的。

**同時交付交叉檢查，而且它有斷言。** 「封閉式模型與真實偵測器一致」是 Measurement 不是 Sweep，所以它設門檻 —— 在數個距離上比對模型預測的公分誤差與真實偵測器經合成影格產生的結果。這是模型與現實分歧時唯一會亮的燈。模型自己站著沒有意義；本 ticket 交付的是「模型是真的，而且證明過跟偵測器一致」。

**Blocked by:** 02 — 先刪掉錯的舊模型，新模型才會從物理推導出發，而不是從舊數字回推。

**Status:** resolved

- [x] Sweep 的感知注入點接受像素抖動參數，公分誤差隨距離平方放大
- [x] 加了抖動的讀數仍走既有整數截斷，模型不比生產管線精確
- [x] 抖動幅度明列為 UNCALIBRATED，敘述不暗示它被量過
- [x] 有測試證明模型**重現了餵給它的抖動**（自我驗證，對齊既有延遲模型的做法）
- [x] 交叉檢查在數個距離上比對封閉式模型與真實偵測器，**有斷言、會失敗**
- [x] 交叉檢查涵蓋的距離足以驗證「隨距離變化的關係」本身，而不只是單一點
- [x] `approach()`、控制律與正式距離管線未被修改
- [x] 新測試在專案 `.venv` 下不 skip，不呼叫 LLM、不需網路或硬體

## Comments

完成於 2026-08-23。`DelayedPerception` 多一個 `jitter_px` 參數，走 Sweep 既有的感知注入點；
`approach()`、`plan_step()` 與 `DistancePipeline` 一行未改（`git status misty_agent/` 為空）。

**兩個實作決定，都不是任意的：**

1. **抖動施加在 `observe()` 而非 `read()`。** 一幀只被偵測一次；若同一幀在每次輪詢時都
   重新抖，`approach()` 的中位數會平均掉真實管線平均不掉的雜訊，Sweep 就會描述一個比實際
   更穩的控制器。有測試釘住這件事。
2. **抖動把臉寬吃掉時整幀不產生讀數。** `DistancePipeline._consume_loop` 在 `not
   face.has_human` 時 `continue`，從不存下未知讀數，前一筆會留在檯面上直到過期。模型照抄
   這個行為，而不是回報 −1。

**挖到兩個真發現：**

**(A) 偵測器有記憶，交叉檢查的第一版量錯了東西。** 孤立靜態影格在 180cm 找不到臉；同一個
偵測器跳著餵（60→90→120→…）改成在 120cm 失敗；2.5cm 步進的連續行走則 55–185cm 整段零漏。
`FaceDetector` 開著跨幀追蹤，而生產環境餵的是 30fps 連續影片。**這是 `PLAN.md` §12.1、
§12.5 之後同一條教訓的第三次**，完整記錄在新增的 §14.7。改用連續輸入後，量到的敏感度與
封閉式預測完全吻合：60→120cm 是 −0.7385 vs −0.7385，90→180cm 是 −1.6615 vs −1.6615。

**(B) 第一版交叉檢查的配對條件數太差。** 用 60→72cm 相減兩個各帶 2% 誤差的讀數，誤差傳遞
到 22%，17% 的偏差量到的是自己的條件數不是模型。改用間距 60cm 與 90cm 的配對降到約 6%。
**容差是從已記載的偵測器精度（`test_the_detector_recovers_the_distance_the_composer_was_given`
的 `rel=0.02`）做誤差傳遞推出來的，不是照觀察到的數字回頭配** —— 實際吻合度遠優於容差。

**交叉檢查拆成兩條主張**：`test_the_real_detector_measures_face_width_linearly` 管「形狀」
（跨 3× 距離範圍、敏感度跨 9×），`test_the_closed_form_matches_what_the_real_detector_does`
管「數值」。前者才是封閉式模型真正賴以成立的假設。另有
`test_the_linearity_probe_spans_enough_range_to_see_the_square` 防止有人日後把範圍縮窄。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **285 passed、零 skip**（272 → 285，
新增 13 條）。無 LLM、無網路、無硬體。

**本 ticket 開始前工作樹的狀況：** 使用者曾在其他對話並行跑 04／06／07，導致 agent 互相
讀到中間狀態；使用者停止全部 agent 後選擇丟棄那些未提交成果（含一個做到一半、前提錯誤的
07 紅測試，以及 `approach.py` 裡一個 mutation check 用的人為缺陷）。本 ticket 從
`25ae831` 的乾淨樹重做，被丟棄的 diff 存在 session scratchpad 的
`discarded-parallel-work.diff`。

---

**Review 後的更正（2026-08-23，同日）。** 兩軸 `/code-review` 都做了 mutation testing，找出
**三個硬缺陷，其中兩個是我的測試根本不會失敗**：

1. **Sweep 接線沒有被測到。** reviewer 把 `_SimulatedWorld` 的 `jitter_px=jitter_px` 改成
   `0.0`，**285 個測試全數照樣通過**。追下去發現接線其實是對的（30px 抖動下讀數從 130 散到
   94–206），問題在於**斷言下在錯的層級**：`approach()` 的中位數真的吸收掉對稱雜訊，所以在
   預設起始距離下 0–80px 的 outcome 完全一樣。新增
   `test_jitter_reaches_the_controller_through_the_sweep`，斷言 seed 之間的分歧 —— 那是
   中位數殺不掉的觀察量。另加
   `test_enough_jitter_makes_the_controller_report_a_success_it_did_not_have`，證明模型**產得出**
   ticket 05 要找的失敗模式（120px 下有 seed 回報 `arrived` 卻走了 0 步停在 130cm，
   truth audit 判 `converged=False`）。這不是門檻：120px 遠大於任何真實抖動，選它是為了明確
   而非臨界。
2. **吞掉臉的那條測試不可能失敗。** 原斷言是 `reading is None or reading > 0`，但 `read()`
   會保留最後一筆值，所以一旦有幀落地就永遠不回 None。改成斷言「較晚的時刻仍解析到較早的
   擷取時間」——那才是「該幀沒留下痕跡」的可觀察證據。
3. **亂數與被掃參數互相污染。** 原本用 instance RNG 依呼叫順序抽，而 `_SimulatedWorld` 的
   priming 幀數隨 lag 增加，於是**同一個 seed 在不同 lag 給出不同的雜訊實現**，二維掃描的
   row 之間不可比。改成以**幀的時間戳**為鍵（`random.Random(f"{seed}:{t!r}")`，字串走
   SHA-512，跨 process 決定性）。新增 `test_priming_the_delay_line_does_not_change_a_frames_wobble`
   釘住它。

**我自己重跑了四個 mutation 確認新測試有牙齒**：丟棄 jitter → 2 紅；不跳過被吞的幀 → 1 紅；
抖動改回依呼叫順序 → 2 紅；抖動改成公分而非像素 → 3 紅。（第一輪我寫的「依呼叫順序」mutation
引用了不存在的屬性，全是 AttributeError 不算數，已重做。）

**三處過度宣稱已改：**

- **「完全吻合」是量化巧合。** 偵測器在 60/120cm 回報 59/119、90/180cm 回報 89/179，差值剛好
  是 60 與 90，相除後與預測逐位相同。真正證明的是「落在 10% 容差內」。`PLAN.md` §14.7 已加警語。
- **容差來源說成「已記載」不精確。** `rel=0.02` 記載的範圍是 72–130cm，而探測點有三個在範圍外。
  改寫成「已記載數字的**外推**」，並說明為什麼不縮小範圍（縮了就看不到 d² 的形狀）。
- **`closed_form` 比想像中弱。** 兩邊都除以同一個 `PX_CM`，所以模型與偵測器**共同**錯的校正
  常數會相消。reviewer 量出它在偵測器尺度誤差 ≥13% 時才紅，且對 0.003×width 以下的形狀漂移
  是瞎的；`linearly` 則在 0.0008×width 就紅。兩者的 docstring 都寫明各自抓得到什麼，並註明
  「不要把 linearly 當成多餘的刪掉」。

**一項判定不改：** reviewer 指出 `focal_length` 與 `real_face_width_cm` 一起傳進
`DelayedPerception` 卻只是相乘成 `_px_cm`（Data Clump），建議直接收乘積。不改的理由是這兩個
是 `config.py` 與 `CONTEXT.md` 的既有詞彙，`_SimulatedWorld` 本來就從 `Settings` 逐欄拿；
收乘積會把「focal length」與「face width」這兩個有物理意義的量塞進一個沒有名字的常數，讀者
反而要回推。這是可讀性與局部簡潔的取捨，選了前者。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **288 passed、零 skip**（285 → 288）。
