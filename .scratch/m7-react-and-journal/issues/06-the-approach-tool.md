# 06 — `approach` Tool

**What to build:** 讓模型能表達「我要靠近這個人」，而完全不知道那是怎麼辦到的。

這是整個專案最站得住腳的設計主張所在（`PLAN.md` §4）：**模型決定要不要靠近，控制層決定這一步走幾公分。** 讓模型自己算「速度 × 時間」正是 README 開頭批判的事。

所以這張票交付的是一層**薄轉接**：Tool 收到一個沒有物理參數的呼叫，轉給 M5 已經驗證過的閉環，把四個狀態原封不動傳回去。**不重寫控制律，不碰控制層的程式碼。**

`back_up` 不在工具集裡：`approach()` 本來就會後退，主體太近時它自己會退（`PLAN.md` §15.2）。

**Blocked by:** 04

**Status:** done

- [x] `approach` 已登記，模型呼叫得到
- [x] 它的參數裡沒有 velocity、timeMs，也沒有目標距離
- [x] 四個既有狀態原封不動傳回給模型，不被重新命名或壓縮
- [x] 控制層與正式距離管線**未被修改**
- [x] 有測試證明送給模型的文字裡不含 velocity 或 timeMs —— 斷言的是**送出去的內容**，不是參數簽名
- [x] 有測試證明主體太近時這個 Tool 會讓機器人後退，而不需要第二個 Tool
- [x] 測試在專案 venv 下零 skip，不需硬體

## Notes（來自 #04 的 review）

- `ToolContext` 已補上 `config` 與 `clock`，就是為了叫得動 M5 的
  `approach(readings, robot, *, config, clock)` —— 不需要改 dispatch 的呼叫慣例。
- 有測試釘住「呼叫端傳進去的 context 就是 handler 拿到的那一個」
  (`test_the_context_the_caller_passed_is_the_one_the_tool_gets`)。
- `approach` 用 `NoArguments`。它**沒有** `extra="forbid"`：dispatch 自己先擋未知參數，
  再設一次是同一條規則的第二份（`PLAN.md` §10）。
- §15.2 明白留著「將來加一個受 clamp 的目標距離參數」這個選項，`layering.py` 因此**不擋**
  `target_distance_cm` 這類名字。這張票仍然不加。


## Comments

完成於 2026-09-02。`misty_agent/agent/tools.py` 加 28 行，`tests/test_approach_tool.py`
40 條測試。全套 **730 passed、零 skip**（713 → 730）。

**六行的 Tool，難的是證明它什麼都沒加。** 四個狀態原封不動傳回，key 用 `result` 而不是
`status`，因為 golden 是這樣寫的、而 golden 寫在前面。

**控制層與感知管線逐位元未改** —— `git diff HEAD -- misty_agent/control/ misty_agent/perception/`
是空的，不是靠斷言，是靠 diff。

**測試檔從 `tests/test_approach.py` import 世界模型**（`MovingWorld`、`TickReadings`、
`WorldThatLosesTheUserAfterAStep`），沒有自己再寫一份。用 M5 驗證時用的同一個世界，本身就是
「這是轉接不是重寫」的證據；再寫一份就是 §10 講的第二份定義。

---

## Review（兩軸）

### 我把一個「等價變異」判斷錯了

我跑的 mutation 把 `outcome.status.value` 換成 `outcome.status`，全綠，我判定等價並寫進紀錄
—— 依據是 `json.dumps` 一樣、`from_jsonl` 往返相等。**Standards 軸指出不等價**：3.11 的
mixin enum，`f"{status}"` 印的是 `ApproachStatus.ARRIVED`，而 `TerminalRenderer` 就是用
f-string。那是一個 Journal 的讀者被騙。**我驗證了序列化和比較，沒有驗證顯示。** 見 §15.17。

### `test_..._says_exactly_what_the_backend_said` 的 docstring 又犯了 §15.9

我寫「任何規劃、重試或平滑化都會在這裡顯示出來」—— 它看不到重試，因為所有 double 都是決定性
的，重試第二次會得到一樣的答案。已改成說清楚抓得到什麼、抓不到什麼，並補一個**第一次失敗、
第二次成功**的 double。§15.18。

### 拒絕理由會洩漏 velocity，而 `_screen` 到不了它

Spec 軸：模型送 `{"linearVelocity": ...}`，拒絕理由把名字**原樣複述**進 Journal 和模型的下一個
Observation。`_screen` 守的兩個都是 mapping，`reason` 是句子。修法兩層（逐字檢查 + 描述而非
複述）記在 §15.16 —— 其中「必須逐字切」是 mutation 才逼出來的：整句丟進去會漏掉每一個時間單位。

### 其他

- `ToolContext.config` 是 None 時，錯誤會從控制層裡拋出來、訊息裡沒有 Tool 也沒有欄位名。
  現在當場擋下並說清楚（§10 #4 換一層出現）。
- Tool 的描述可以偷渡安全承諾（mutation 換成「Guaranteed never to hit them」全綠）—— §8 最後
  一條說 `approach()` 從未在真機跑過。補了一條測試擋掉這類措辭。
- 「沒有第二個 back_up」原本寫成「名字裡不能含 back」，比 §15.2 要求的寬鬆度更嚴，已收窄。

**Mutation：兩輪。** 第一輪 15 個 13 紅、1 個是我自己寫壞的錨點、1 個是我誤判的等價變異。
補完兩軸的發現後第二輪 **14/14 全紅**。

其中「Tool 把所有失敗吞成 arrived」第一次存活，因為 `approach()` 自己就會把機器人的例外接成
`drive_error`，包在外面的 try/except 在正常情境下**根本不會被觸發**。要一個從外面來的失敗才
測得到 —— 而 ticket 08 的緊急停止正是那種。
