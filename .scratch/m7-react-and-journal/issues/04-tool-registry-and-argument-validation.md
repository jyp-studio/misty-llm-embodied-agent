# 04 — Tool 註冊表與參數驗證

**What to build:** 讓一個 Tool 可以被登記、被宣告給模型、被呼叫；而不合法的參數在送到機器人**之前**就被擋下來。

**參數用型別定義，schema 由型別產生。** 一份定義同時負責宣告與驗證，兩者不會漂 —— 這個 repo 已為「兩份會各自漂移」做過至少三次決定。手寫第二份 schema 是本票明確禁止的。

**這還掉 `PLAN.md` §14.6 欠的一筆帳**：「超出範圍或未知的工具參數要被拒絕，而不是送到機器人」。M6 刪掉舊 runner 時帶走了這個覆蓋。

拒絕本身要成為一筆 Journal 紀錄 —— 模型送了什麼、為什麼被擋，事後要查得到。

用 `done` 當曳光彈：它是最簡單的 Tool，足以把「登記 → 宣告 → 呼叫 → 記錄」整條路打穿。

**Blocked by:** 01

**Status:** resolved

- [x] Tool 以註冊表登記；新增一個 Tool 不需修改 ReAct 迴圈
- [x] 參數型別是唯一的定義來源，模型看到的 schema 由它產生
- [x] 超出範圍或未知的參數在送達驅動層**之前**被拒絕
- [x] 被拒絕的呼叫成為一筆 Journal 紀錄，含 Tool 名稱與被拒的原因
- [x] `done` 端到端跑通：登記、產生 schema、被呼叫、留下紀錄
- [x] 有測試證明合法值會過**且**不合法值會被擋 —— 只測前者等於沒測
- [x] 沒有任何手寫的第二份 schema
- [x] 測試在專案 venv 下零 skip，不呼叫模型

## Comments

完成於 2026-08-25。`misty_agent/agent/tools.py`：註冊表、schema 產生、參數驗證、dispatch，
以及 `done` 這個曳光彈。

**一份定義同時負責宣告與驗證。** 模型看到的 schema 由參數型別產生（`model_json_schema()`），
擋下超範圍的也是同一個型別。有測試把這件事釘死：從 schema 讀出上界，用那個值與那個值加一
各呼叫一次，斷言前者過、後者被擋 —— 兩者若有一天分家，這條會紅。**沒有任何手寫的第二份 schema。**

**驗證在送達驅動層之前。** dispatch 的順序是「驗證 → 記錄 → 執行」，有測試證明被拒絕的呼叫
**handler 一次都沒被進入**（收集器是空的），而不是只證明它回傳了失敗。

**未知參數由 dispatch 自己擋，不靠每個模型作者記得設 `extra="forbid"`。** 一條每個作者都要
記得的規則，遲早會有人忘記；而靜靜丟掉一個參數會讓模型以為它起了作用。

**註冊時就拒絕物理控制參數。** Journal 已經拒絕**記錄** velocity 或 timeMs；拒絕**登記**才是
讓它從一開始就不可能 —— 否則模型會在它拿到的 schema 裡被告知可以送。附一條陰性對照（正常參數
仍要註冊得起來），否則一個「拒絕一切」的檢查也會通過。

**`ends_episode` 是註冊時宣告的屬性，不是從名字猜的。** `PLAN.md` §4 禁止硬編碼快路徑，
而一個去比對字串 `"done"` 的迴圈就是一條。

**兩個實作中途發現的問題：**

1. **`get_type_hints` 解析不到函式內定義的型別**（測試檔有 `from __future__ import annotations`，
   註解是字串）。原本會拋出一個裸的 `NameError`，看不出要怎麼辦。改成明說「參數型別必須在
   模組層級可達」，並補測試。
2. **記錄的是驗證**後**的參數，不是原始請求。** 兩者在型別強制轉換時會不同，而記原始請求的
   Journal 會與機器人實際收到的指令不符。有測試餵 `{"pitch": "10"}` 並斷言記下的是 `10`。

**Mutation testing（隔離 worktree、harness 先自我檢查）：** 不驗證直接呼叫、不擋未知參數、
被拒絕時「也」記一筆 tool_called、被拒絕時完全不記、記原始參數、不擋控制參數、重複名稱不擋、
不要求宣告參數型別、`ends_episode` 一律 False、先呼叫 handler 再記錄、理由不說明哪個參數、
schema 不含 description、schema 不含界限、未知工具的理由不列出現有工具 —— **十四個全部變紅**
（這行原本寫「十五個」，數目與列出的對不上，review 抓到）。

**其中一個我回頭重做過。** 第一輪「被拒絕時也記 tool_called」是被一條**不相干**的測試抓到的
—— 因為我的 anchor 寫錯，那個 mutation 其實與「記原始參數」是同一個。單獨重做後，名副其實
的 `test_a_refused_call_is_not_also_recorded_as_a_call` 確實會紅。

**這還掉 `PLAN.md` §14.6 的第二筆帳**（工具參數的合法性檢查）—— M6 刪掉舊 runner 時帶走的
覆蓋。§14.6 的標記待 ticket 12 一併更新，因為 memory 那筆要等 ticket 09。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **487 passed、零 skip**（460 → 487）。

---

## Review（兩軸，各自隔離 worktree）

兩軸**各自獨立**跑出同一個最重要的結果，而且它推翻的正是上面那句自誇。

### 1. `ends_episode` 那條，測試根本測不出來

把 `ends_episode=tool.ends_episode` 換成 `ends_episode=(name == "done")` —— **完全不會紅。**
因為 `build_registry()` 裡唯一 `ends_episode=True` 的 Tool，同時也是唯一叫 `done` 的 Tool。
`test_done_says_the_episode_should_end` 的 docstring 明寫「§4 禁止硬編碼快路徑」，它自己卻是
那個 mutation 的通過證明。補了兩條：一個**不叫** `done` 卻會結束的 Tool，一個**叫** `done`
卻不會結束的 Tool。寫進 `PLAN.md` §15.9。

同一個形狀的還有 `ToolContext`：沒有任何測試斷言呼叫端傳進去的 context 到得了 handler，換成
當場新建的空 context 不會紅 —— 而那是 05/06 唯一碰得到機器人的路徑。

### 2. 拒絕理由產不出 golden（Spec 軸；Standards 軸看不到這個）

golden 寫 `"pitch 140 is outside the permitted range"`，`_explain()` 產
`"pitch: Input should be less than or equal to 26"`。欄位對得上、內容對不上，而 ticket 07
必須重現那個檔案。**實作讓步**，理由與那條把實作釘死在 golden 對面的測試
（斷言 `"26" in reason`）都記在 `PLAN.md` §15.7。新測試直接**從 golden 檔案讀出**字串比對。

### 3. 分層守衛擋不住任何真的想繞過它的人

- `velocity_cm_s`、`speed`、`duration_ms`、`drive_time_ms` **全部註冊得起來**（原本是六個
  拼法的精確比對）。
- `Field(alias="linearVelocity")` 註冊得起來，而且 `linearVelocity` **會出現在模型看到的
  schema 裡** —— 正是 docstring 宣稱不可能的事。然後 dispatch 把每次呼叫都當未知參數拒絕：
  一個看得到、永遠叫不動的 Tool。
- 巢狀模型的欄位根本不在 `model_fields` 裡。

規則移到 `misty_agent/agent/layering.py`（`journal.py` 與 `tools.py` 原本各有一份，正是 §10
講的事），註冊時檢查的對象改成**產生出來的 schema**。細節與那張方向表在 `PLAN.md` §15.8。

**這裡我把規則放太寬過一次，是 golden 擋下來的。** 第一版「結尾是時間單位就拒絕」讓四個 golden
全掛 —— Observation 的 `estimated_speech_ms` 和 `latency_ms` 是**系統回報的量測**，不是模型
下的命令。規則因此分方向。

### 4. 順手修掉的

- Tool 名稱沒有任何限制，`""` 和 `"move head!  "` 都註冊得起來 —— 會在網路呼叫的另一端才被拒。
- 參數型別的 docstring **會被 pydantic 放進 schema 送給模型**，模型會讀到這個模組關於
  `PLAN.md` §10 的內部說明。`Tool.schema()` 現在把它拿掉。
- `NoArguments` 的 `extra="forbid"` 是死的（dispatch 先擋未知參數），移除。
- `_explain` 只回報第一個錯誤 → 模型得一個 Turn 修一個參數。改成全部回報。
- `Sequence` 未使用；`_argument_type` 伸手進 `handler.__code__` → 改用 `inspect.signature`。
- `ToolContext` 補上 `config` 與 `clock`：M5 的 `approach(readings, robot, *, config, clock)`
  就是這個 context 必須叫得動的簽章，§15.4 的抑制窗也需要 clock。

### 5. 重跑 mutation

十八個，涵蓋上面每一條加上新程式碼 —— 第一輪 16/18，兩個活的都是真的缺口（時間單位的「最後
一段」規則沒有陰性對照；Journal 兩個呼叫點的方向沒有被釘死），補測試後 **18/18 全紅**。

**寫 harness 時我踩到自己警告過 reviewer 的那個坑**：zsh 的 noclobber 讓 `cat > layering.py`
靜靜失敗，檔案沒被寫進去，於是 104 個測試爆掉。用 `>|` 才寫得進去。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **587 passed、零 skip**（487 → 587）。
