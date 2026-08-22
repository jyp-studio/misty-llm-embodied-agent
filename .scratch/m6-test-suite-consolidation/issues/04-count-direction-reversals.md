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

---

**Review 後的更正（2026-08-23，同日）。** 兩軸 `/code-review` 找出的問題比前一張票更重，
其中兩類是我自己的 mutation testing 沒有覆蓋到的：

**(1) 我在 shipped code 與 §14.8 裡寫了一句假話，而且它與同一段的表格自相矛盾。**
原文說「inside the configured travel multiplier this is zero at every swept lag. Every
reversal reported is a run that left the calibration assumption behind.」——後半是假的。
掃 61 個 lag：**1.5×（假設範圍內）有 12 個 lag 反轉**，集中在 1.85–2.40s；2.0×（configured）
才是 0/61。正確的說法是「在 **configured 倍率**下為零」，那是關於一個倍率的事實，不是關於
它所代表的假設。已更正 `ApproachOutcome.direction_reversals` 的註解與 §14.8。

**(2) 我宣稱 2.0× 配 2 秒 lag 是「全表最糟的安全結果」——用我自己的表就能反駁。**
2.5× 在同樣 lag 下到 −44.9cm，比 2.0× 的 −9.9cm 糟得多。論點（乾淨的反轉數不是安全結論）
成立，最高級不成立。已刪掉。

**(3) §14.8 的結果欄用 raw status，掩蓋了越線。** 表中四列 truth-audit 之後**全部**是
`safety_floor_breach`，而 raw 欄的 `arrived` 與 `timeout` 兩者都看不出來。§13.3 第 1 點
另存 truth-audited outcome 的理由正是這個。已補上該欄。

**(4) 四個 mutation 存活，而且是我沒試過的四個。** reviewer 試了：只算前進→後退（7→4）、
只算後退→前進（7→3）、從不更新 `_last_direction`（2→3）、`_last_direction` 初值設為 1
（後退優先的 run 會多算一次）。**全部 295 passed。** 原因是我所有斷言都是 `>= 1`、`== 0`
或不等式，**沒有任何測試釘住確切數字** —— 而 §14.8 publish 出去的正是確切數字。補了
`test_the_published_reversal_counts_are_what_the_code_produces`（釘住四組）與
`test_a_run_that_backs_up_first_does_not_start_with_a_free_reversal`（起點 20cm，先後退）。
重跑六個 mutation，全部被抓到。

**(5) 兩條測試不可能失敗。** `test_every_swept_row_reports_a_reversal_count` 只斷言
`isinstance(int)` 與 `>= 0`，而欄位的 `= 0` 預設值本身就滿足 —— 拿掉接線它照樣綠。
`test_a_run_that_never_moved_cannot_have_reversed` 斷言 `steps == 0`，根本沒有命令到達
計數器。前者改成掃一個會反轉的倍率並比對，後者改名為
`test_a_run_that_never_moved_reports_no_reversals` 並註明它是邊界不是計數器測試。

**(6) `test_lag_alone_does_not_make_the_controller_reverse` 與陰性對照逐字重複** ——
`speed_error=None` 解析成 `max_actual_motion_multiplier` 就是 2.0，lag 清單也是子集，
兩者跑的是同一批模擬。已併除，被推翻的預測改記在陰性對照的 docstring 裡。
**順帶一提：我當初用來發現「誤刪測試」的 mutation 訊號，有一部分正是這兩條一起變紅造成的。**

**(7) `CONFIGURED_MULTIPLIER = 2.0` 把 config 寫死。** 改成讀
`SETTINGS.max_actual_motion_multiplier`，否則改 config 之後這個名字會說謊。

**(8) 模組 docstring 說「no test asserts a limit on it」現在不完全成立。** 已補一段說明：
釘住的是**完全指定情境下的計數器**（固定 lag + 固定倍率 = 決定性的一次執行），那是模型的
性質，不是對 envelope 落點的主張。

**兩項判定不改：** ①計數在 `drive_time` 的 2xx 檢查之前遞增，理論上被拒絕的命令會動到
計數器而 `steps` 不動 —— 但這個世界從不拒絕命令，已在程式碼註解寫明「會拒絕的世界必須改
在拒絕檢查之後計數」。②`harness/report.py` 尚未輸出這個欄位 —— ticket 04 的範圍明寫
「不負責報告怎麼呈現」，那是 ticket 05。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **296 passed、零 skip**。
