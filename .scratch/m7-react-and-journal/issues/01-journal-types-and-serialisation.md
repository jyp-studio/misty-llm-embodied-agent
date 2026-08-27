# 01 — Journal 的型別與序列化

**What to build:** 讓一份 Journal 可以被建立、寫成文字、再讀回來，而且來回之後一模一樣。

**每種事件一個 frozen 型別。** 共同欄位只有三個：時間、事件種類、Episode 識別。**`turn` 不是共同欄位** —— Episode 開始那一筆沒有 Turn，硬塞會逼出一個 Optional，然後每個讀者都要處理它。

**時間是 Episode 相對秒，來自單調時鐘，而時鐘可以注入。** 沿用控制層已經在用的 Clock protocol 與假時鐘。這不是為了優雅：golden files 要逐字元比對，絕對時間就不可能。Episode 開始那一筆額外帶**一個**絕對 wall-clock 戳記給人對時 —— 只有一個，所以不影響其餘的可比對性。

**契約是那些型別，JSONL 只是序列化格式。** 版本欄位只放在 Episode 開始那一筆（一個 Journal 對應一個 Episode，檔案是整份讀的）。M10 之前 schema 不保證穩定，而且要在文件裡明講這件事。

序列化必須是純函式：不碰檔案、不碰時鐘、毫秒級可測。M6 的報告層是既有先例。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] 每種值得記錄的事件各有一個 frozen 型別；共同欄位只有時間、種類、Episode 識別
- [x] `turn` 只出現在真的有 Turn 的事件上，不是共同欄位
- [x] 時間是 Episode 相對秒，來自單調時鐘，時鐘可注入
- [x] Episode 開始那筆額外帶一個絕對 wall-clock 戳記與 schema 版本
- [x] 型別 → JSONL → 解析回型別，來回結果與原本相同
- [x] 序列化是純函式，不做 IO，不讀真實時鐘
- [x] 沒有任何欄位或型別洩漏 velocity 或 timeMs
- [x] 文件明寫 M10 之前 schema 不保證穩定
- [x] 測試在專案 venv 下零 skip，不呼叫模型、不需網路

## Comments

完成於 2026-08-24。新增 `misty_agent/agent/`，只有型別與序列化，沒有 IO。

**九種紀錄**：Episode 開始／Turn 開始／模型呼叫／Tool 呼叫／Tool 被拒／Observation／
收到停止要求／Episode 中止／Episode 結束。

**中止刻意拆成兩筆。** `StopRequested` 由「注意到」的那條執行緒當下寫，`EpisodeAborted` 由
迴圈收尾時寫。**兩者的時間差就是中斷延遲** —— 那正是 §15.3 選「加鎖直接寫」而非「丟佇列由
主迴圈收」的理由，也是 ticket 02 與 08 要量的東西。

**結束只有一種紀錄型別**（`EpisodeFinished` 帶 outcome），不是每種結局一個型別。這樣
「每個 Episode 剛好結束一次」是一個**用數的就能查**的性質。

**實作中途改了一個設計。** 第一版因為繼承加 dataclass 的欄位順序規則，被迫給每個欄位預設值
——結果 `ToolCalled(t=0, episode_id="x")` 建得起來，而 `args` 型別寫 `Mapping` 預設卻是
`None`。那是一個會說謊的紀錄。改用 `kw_only=True`（Python 3.11 有）之後必填欄位就不需要
假預設值，並補了兩條測試釘住它：缺資料要建構失敗、位置參數要被拒（否則欄位順序會變成契約的
一部分）。

**Mutation testing（隔離 worktree）**：未知型別靜默略過 → 紅；缺欄位不檢查 → 紅；
多餘欄位不檢查 → 紅；時間不四捨五入 → 紅；時間改用絕對值 → 紅；schema 版本假裝穩定 → 紅；
紀錄加一個 `linearVelocity` 欄位 → 兩條禁令測試都紅。

**過程中抓到自己一次。** 第一輪 mutation 的還原機制壞了（zsh 的 noclobber 擋掉重導），
mutation 累積導致結果不可信；重做後發現「多餘欄位不檢查」其實是被一條**不相干**的測試抓到的
——也就是那條分支根本沒有覆蓋。補了 `test_a_record_with_an_unexpected_field_is_refused`
再驗，這次是名副其實的那條紅了。

**匯入乾淨度**：`journal` 不需要 mediapipe、opencv 或 openai 就 import 得起來，維持 M3 立下
的規矩（重相依只在 adapter 內部）。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **352 passed、零 skip**（329 → 352）。
