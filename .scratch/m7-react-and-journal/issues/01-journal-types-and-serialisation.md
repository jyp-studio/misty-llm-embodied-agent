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

---

**Review 後的更正（2026-08-24，同日）。** 兩軸序列跑、各自隔離 worktree。找到**四個存活的
mutation**與五處設計問題，其中一個是這張票最重要的斷言其實擋不住它要擋的東西。

**(1) 最重要的：那兩條「不洩漏 velocity」的守衛，擋不住唯一真實的洩漏路徑。**
一條掃**宣告的欄位名**，一條掃**我自己寫的 fixture** —— 而 fixture 的 `args` 是空字典。
所以 `ToolCalled(tool="approach", args={"linearVelocity": 20, "timeMs": 1500})`
序列化得乾乾淨淨，兩條測試全綠。`args` 與 `payload` 是自由形式的映射，由 04–06 填，
**那就是 `PLAN.md` §4 的核心主張唯一會被打破的路徑**，而它沒有守衛。

改成**在建構時篩檢**（不是序列化時）：不該存在的紀錄不該建得起來。篩檢遞迴進巢狀映射，
並附一條陰性對照（正常參數要過得去，否則一個「拒絕一切」的實作也會通過三條測試）。

**(2) 四個 mutation 存活。** `EpisodeClock` 快取 elapsed 值（**沒有任何測試呼叫它兩次**，
而迴圈是每筆紀錄呼叫一次 —— 所有 `t` 會凍在零而全綠）、拿掉結尾換行（`splitlines()` 看不見，
但 02 逐筆 append 會把兩筆黏成一行）、`sort_keys=False`、`ensure_ascii=True`。後兩者是
**ticket 03 逐字元比對的前提**，而我的 fixture 全是 ASCII 與空字典，分不出穩定與不穩定。
fixture 已改成帶中文語音與巢狀結構。

**(3) `EpisodeAborted` 是多餘的第三筆。** 它唯一的欄位 `reason` 與 `StopRequested.source`
是同一個事實，於是一次結束有三筆紀錄、一個事實存兩份。**移除**，中止改由
`EpisodeFinished(outcome="aborted")` 承載。「每個 Episode 剛好結束一次」現在是**用數的就能查**
的性質，並有測試釘住只有一種終結型別。

**(4) `Snapshot` 原本藏在一個無型別的袋子裡。** 它在 glossary 裡是「刻意固定為三樣」，
而 `Observation.payload` 讓那三樣無法被斷言。拆成 `result`（每個 Tool 不同，開放）與
`snapshot`（固定三樣，型別化）—— 這正是 §15.4 那條「上半開放、下半固定」的切法，現在型別
上看得見。

**(5) `outcome` 是不受限的字串。** spec 列了四種結束方式，程式碼裡一個都沒有。加上 `OUTCOMES`
並在建構時驗證。順帶釐清一件會誤導人的事：**四個 golden 場景對應三個 outcome** ——
「第一個 Turn 就結束」與「多個 Turn 後結束」都是模型自己選擇停止。已寫成測試。

**其餘更正**：`_Record` 改為公開的 `Record`（它出現在公開簽名裡）；基底不再給 `type` 預設值
（忘了覆寫現在是建構錯誤，不是靜靜序列化成 `"record"`）；非 JSON 原生值在建構時被拒
（tuple 回來會變 list，靜靜破壞與 golden 的比對）；`TIME_PLACES` 的註解補上「它同時是中斷
延遲的量測下限」。

**一項判定不改：** reviewer 指出 `Clock` 與 `_SystemClock` 與控制層重複。判定是**保留但把
docstring 改成說實話** —— 它是**刻意更窄**的形狀（Journal 從不等待，要求 `sleep` 會逼每個
呼叫端提供一個用不到的方法），而原本寫「the same shape」是不精確的。控制層的時鐘滿足這個
protocol，所以兩者相容。

**重跑七個 mutation：全部變紅。**

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **367 passed、零 skip**（352 → 367）。
