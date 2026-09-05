# 11 — 真模型測試改造成不變量斷言

**What to build:** 讓「用真模型跑一次」這件事從「印出來給人讀」變成「會失敗的測試」。

現有的那份腳本呼叫真模型、印出決策與每個硬體呼叫，**零斷言**。它證明不了任何事，而且不能進 CI —— 一進去就是會抽風的 gate，而 M6 #08 剛示範過抽風會怎麼侵蝕「全綠零 skip」這句話的價值。

**掛 marker、預設排除、斷言性質不是字串。** 可以當 gate 的是那些不管模型怎麼換句話說都必須成立的東西：

- Turn 上限沒有被突破
- Episode 一定終止並回到閒置
- 模型從未收到 velocity 或 timeMs
- 所有 Tool 參數都在範圍內
- `approach` 只走確定性後端

**不能當 gate 的**（例如「使用者難過時表情是否合宜」）分開報通過率，不掛在紅綠燈上。

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] 測試掛 marker，預設被排除，CI 的預設跑法不會呼叫模型
- [ ] 斷言的是 Journal 上的不變量，不是模型講了哪些字
- [ ] 至少涵蓋：Turn 上限、必定終止、模型未收到物理參數、Tool 參數在範圍內
- [ ] 行為品質類的觀察分開報告通過率，不當 gate
- [ ] 被明確選取但沒有 API key 時，訊息說明怎麼提供，而不是丟一個難懂的錯誤
- [ ] 舊的那份「印給人看」的腳本不再存在
- [ ] 預設測試在專案 venv 下零 skip


## Notes（來自 #07）

- 窄介面就是 `misty_agent/agent/react.py` 的 `Model` protocol：`decide(working_context,
  tools) -> Decision`。這張票要做的是一個真的實作，加上 `@pytest.mark.llm_live`。
- `tests/test_react.py::ScriptedModel` 是離線那一側，斷言的是 Journal 上的不變量 ——
  這張票要斷言的也是同一批不變量，不是模型說了什麼。


## Notes（來自 07–10 補跑的 review）

- **`llm_live` marker 還沒在任何地方註冊。** `tests/conftest.py` 是受保護檔案，不能改，
  所以 marker 要註冊在哪裡是這張票的第一個決定（`pyproject.toml` 的
  `[tool.pytest.ini_options] markers` 是最可能的位置）。沒註冊的話 pytest 會發
  `PytestUnknownMarkWarning`，而且 `-m "not llm_live"` 過濾不會如預期。
- 窄介面是 `misty_agent/agent/react.py` 的 `Model` protocol：
  `decide(working_context, tools) -> Decision`。
- 離線那一側是 `tests/test_react.py::ScriptedModel`，斷言的是 Journal 上的不變量 ——
  這張票要斷言的是同一批不變量，不是模型說了什麼。
