# 06 — `approach` Tool

**What to build:** 讓模型能表達「我要靠近這個人」，而完全不知道那是怎麼辦到的。

這是整個專案最站得住腳的設計主張所在（`PLAN.md` §4）：**模型決定要不要靠近，控制層決定這一步走幾公分。** 讓模型自己算「速度 × 時間」正是 README 開頭批判的事。

所以這張票交付的是一層**薄轉接**：Tool 收到一個沒有物理參數的呼叫，轉給 M5 已經驗證過的閉環，把四個狀態原封不動傳回去。**不重寫控制律，不碰控制層的程式碼。**

`back_up` 不在工具集裡：`approach()` 本來就會後退，主體太近時它自己會退（`PLAN.md` §15.2）。

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] `approach` 已登記，模型呼叫得到
- [ ] 它的參數裡沒有 velocity、timeMs，也沒有目標距離
- [ ] 四個既有狀態原封不動傳回給模型，不被重新命名或壓縮
- [ ] 控制層與正式距離管線**未被修改**
- [ ] 有測試證明送給模型的文字裡不含 velocity 或 timeMs —— 斷言的是**送出去的內容**，不是參數簽名
- [ ] 有測試證明主體太近時這個 Tool 會讓機器人後退，而不需要第二個 Tool
- [ ] 測試在專案 venv 下零 skip，不需硬體

## Notes（來自 #04 的 review）

- `ToolContext` 已補上 `config` 與 `clock`，就是為了叫得動 M5 的
  `approach(readings, robot, *, config, clock)` —— 不需要改 dispatch 的呼叫慣例。
- 有測試釘住「呼叫端傳進去的 context 就是 handler 拿到的那一個」
  (`test_the_context_the_caller_passed_is_the_one_the_tool_gets`)。
- `approach` 用 `NoArguments`。它**沒有** `extra="forbid"`：dispatch 自己先擋未知參數，
  再設一次是同一條規則的第二份（`PLAN.md` §10）。
- §15.2 明白留著「將來加一個受 clamp 的目標距離參數」這個選項，`layering.py` 因此**不擋**
  `target_distance_cm` 這類名字。這張票仍然不加。
