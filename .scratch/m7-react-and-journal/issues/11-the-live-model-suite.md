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

**Status:** done

- [x] 測試掛 marker，預設被排除，CI 的預設跑法不會呼叫模型
- [x] 斷言的是 Journal 上的不變量，不是模型講了哪些字
- [x] 至少涵蓋：Turn 上限、必定終止、模型未收到物理參數、Tool 參數在範圍內
- [x] 行為品質類的觀察分開報告通過率，不當 gate
- [x] 被明確選取但沒有 API key 時，訊息說明怎麼提供，而不是丟一個難懂的錯誤
- [x] 舊的那份「印給人看」的腳本不再存在
- [x] 預設測試在專案 venv 下零 skip


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


## Comments

完成於 2026-09-05。根目錄的 `test_llm_live.py` 已刪除，換成
`tests/test_llm_live.py`（7 條，掛 marker、預設排除）、`tests/episode_invariants.py`
（七條不變量）、`tests/test_episode_invariants.py`（30 條，離線證明每條都會紅）、
`misty_agent/agent/model.py`（真模型，窄介面的唯一實作）、`tests/test_model_adapter.py`
（25 條，不 mock SDK）、`pytest.ini`。**939 passed、7 deselected、零 skip。**

**gate 是不變量，不是模型講了什麼。** 細節與 marker 放 `pytest.ini` 的理由記在 §15.32。

**每條 gate 都在離線證明過會紅** —— 這是關鍵：一條空洞的檢查在一套沒人跑的付費測試裡會永遠
綠，而那正是這張票要終結的事。

**成本：worst case 34 次模型呼叫，約 0.09 美元**（典型約 0.03）。

---

## Review（兩軸）

### Spec 軸：`approach` 的檢查在 live 是空的

我給 live 用的 reading source 把 `frame_arrived_at` 標成 0.0，而注入時鐘也在 0.0 ——
**每一筆讀數都是過期的**，`approach` 永遠回 `lost_user`、0 個 Step，於是「每次驅動都來自
控制器」永遠只是在比 `0 == 0`。離線有牙齒、上線沒有。改用 M5 的 `MovingWorld`，並補一條
「至少有一個情境真的動了」當陰性對照。§15.33。

### Spec 軸：沒有 key 的訊息叫人做一件沒用的事

我寫「把 key 放進專案的 `.env`」—— 但 `Settings` 只讀 `.env` 裡 `MISTY_` 開頭的欄位、
**從不匯出到環境變數**，而 `.env.example` 第 6 行本來就寫著「不要把 OpenAI key 放這裡」。
而且我寫了 `assert ".env" in message` 把錯誤建議**鎖了起來**。改成 `export OPENAI_API_KEY=`，
並補一條實際建 `.env` 證明它沒用的測試。

### Spec 軸：24 次呼叫只為了印報告

行為報告把三個情境再跑一次。改成共用 gate 已經跑過的 Episode，58 → **34 次**。

### Standards 軸：兩條我自己犯的規

**§15.20**：`every_drive_came_from_approach` 又去挖 `result["steps"]` 字串鍵 —— 而 §15.20
正是為了「不要再有人去挖它」才存在的。改用 `EpisodeFinished.steps`。

**§10**：`FORBIDDEN_IN_PROMPT` 號稱是獨立的「第二意見」，實際是**有損拷貝** ——
`speed`、`driveSpeed`、`cmPerSec`、`driveDuration` 全都漏了，而且 `cm_per_sec` 用底線寫、
守衛卻正規化 camelCase，所以 Misty API 真正用的拼法會溜過去。改成先攤平再比對，並加一條
meta 測試斷言它至少和守衛一樣嚴。

### Standards 軸：11 個存活的 mutation，系統性原因只有一個

`BROKEN` 是**每個 check 一個破壞**，但七條 check 裡有五條含多個獨立子句 —— 於是子句層級
從沒被證明過會紅，11 個存活裡有 6 個出自這個。改成**每個子句一個破壞**（14 個），而且斷言
「只有那一條 check 會叫」。改完之後又抓到兩條子句**互相掩護**：把「超過上限」寫成
`turn=99` 同時也破壞編號，所以放寬上限比較的 mutation 一直被編號那條蓋掉。

另外兩個是 §10 #4 的老毛病：`temperature` 與 `model` 宣告了、讀進來了、**沒有測試證明它們
真的送出去** —— 刪掉它們什麼都不會紅。

補完之後 **14/14 全紅**。

### 額外加的一條保險

`test_the_live_harness_produces_an_episode_that_passes_its_own_gates` —— 用腳本化模型離線跑
一次 live 套件的 `a_live_episode`。付費套件沒人會順手跑，所以壞掉會一直壞著直到有人付錢才
發現；上面那個 reading 的坑就是這樣躲過去的。
