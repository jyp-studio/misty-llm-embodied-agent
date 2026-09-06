# 03 — 系統提示

**What to build:** 讓模型知道自己是誰。

舊主腳本的 `SYSTEM_PROMPT` 在 M7 #12 隨檔案一起被刪掉，而 `HANDOFF.md` 當初訂的條件是
「prompt 與 memory 搬出後才刪」—— memory 在 #09 搬了，**prompt 沒有**。所以現在
`run_episode` 組出來的 working context 裡只有觸發、模型自己的決定、Observation 和拒絕理由：
模型不知道自己是一個機器人，也不知道使用者的話來自有雜訊的語音轉錄。

繼承舊提示裡兩件仍然成立的事（身分、ASR 有雜訊不要照字面理解），丟掉 JSON 輸出格式那整塊
（function calling 取代了它），加上 ReAct 才需要的：只能透過 Tool 行動、`done` 是自己的選擇、
以及分層。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 提示放在自己的模組，**不放 `config.py`** —— 它是內容不是可調參數，一段散文塞進
      `Settings` 會讓那份設定變質
- [ ] `run_episode` 取回 `instructions=` 參數。#11 移除它是因為零呼叫端零測試（`PLAN.md`
      §15.23）；**這次兩者都要有**
- [ ] 有測試證明模型真的讀到它（斷言 working context，不是斷言常數存在）
- [ ] **提示中不含任何物理控制參數**，用既有的 `layering` 與 `episode_invariants` 稽核，
      連同九個 Tool 的 schema 一起比對
- [ ] 提示**不使用 `Step` 這個詞** —— 它是 `CONTEXT.md` 裡控制層的詞彙，教給模型等於讓模型
      用控制層的詞思考
- [ ] 陰性對照：一個空提示或一個沒被送出的提示會讓測試變紅
- [ ] 全套測試綠且零 skip
