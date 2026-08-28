# 03 — 四份 golden Journal，先於迴圈

**What to build:** 把「一次 Episode 應該長什麼樣」寫成四份對照檔，**而且在 ReAct 迴圈存在之前就 commit**。

**這張票是整條 ticket 鏈裡防作弊的那一環。** Journal 是 M7 測試的斷言標的。如果它與迴圈在同一批工作裡長出來，斷言的詞彙就會被實作反向塑形 —— 會寫出「剛好會過」的測試。所以 schema 從 spec 推導，不從實作推導，而 git 歷史是這件事唯一的客觀證據（`PLAN.md` §15.6）。

**四份，因為 Episode 只有四種結束方式：**

1. 一個 Turn 就結束（模型第一次就選擇結束）
2. 多個 Turn 正常完成
3. 撞到 Turn 上限被強制停下
4. 被緊急停止中止

少一種，就有一條路徑沒有對照。

此時還沒有東西能**產生**這些檔案，所以本票驗證的是另外兩件事：每一份都解析得回 01 的型別，以及比對用的輔助函式真的指得出兩份 Journal 第一個不同的地方。

**Blocked by:** 01

**Status:** resolved

- [x] 四份 golden 各對應 Episode 的一種結束方式，沒有遺漏
- [x] 每一份都由 spec 推導；實作此時尚不存在
- [x] 每一份都解析得回 01 的型別，欄位齊全
- [x] 有比對輔助函式，失敗時指出第一個不同的位置與內容，而不是只說「不一樣」
- [x] 本 ticket 的 commit 早於 ReAct 迴圈的 commit
- [x] 檔案或其說明裡明寫：實作若產不出某份 golden，改哪一邊要記回 `PLAN.md`，不是默默改 golden 去配合程式碼
- [x] 測試在專案 venv 下零 skip

## Comments

完成於 2026-08-25。四份 golden 在 `tests/goldens/`，加上一份說明規則的 README，以及
`first_difference()` 比對輔助函式。**ReAct 迴圈此時仍不存在** —— `git log` 就是證據。

**四份檔案、三種 outcome。** 「第一個 Turn 就結束」與「多個 Turn 後結束」都是模型自己選擇
停止；它們是兩份檔案因為它們是**迴圈裡兩條不同的路徑**，不是兩種不同的結束。有測試把這個
不對稱釘住，免得日後有人以為少了一種。

**這些檔案釘住了三個只寫在這裡的決定**（README 有完整說明）：

1. **`done` 只產生 `tool_called`，不產生 `observation`。** Observation 是模型用來決定下一個
   Turn 的東西；`done` 之後沒有下一個 Turn，記一筆等於記給沒有人看。
2. **Turn 上限讓最後一個 Turn 跑完。** 上限擋的是第六個 Turn 開始，不是把第五個切斷。所以
   那份 golden 有五個完整的 Turn 然後才結束。
3. **中止不丟掉已經做完的工作。** 停止從另一條執行緒在 Tool 執行到一半時抵達，而 Python
   無法中斷一個還沒返回的呼叫。所以 Tool 跑完、Observation 記下來，之後 Episode 才以
   `aborted` 結束。`stop_requested` 到 `episode_finished` 的間隔就是中斷延遲 —— 那正是
   §15.3 讓它們是兩筆而不是一筆的理由。

**第三點是三個之中最不確定的**，README 也這樣寫。它是 ticket 08 要去確認的事；若結果不同，
**那份檔案要改，而且 `PLAN.md` 要說明為什麼** —— 不是默默改 golden 去配合程式碼。

**比對的是紀錄，不是位元組。** §15.3 說契約是型別、JSONL 是序列化格式，所以
`first_difference()` 比的是解析後的紀錄，並指出**第幾筆、哪一種、哪個欄位、兩邊各是什麼**。
格式另外用 round-trip 測試釘住（`to_jsonl(from_jsonl(text)) == text`），這樣鍵序或編碼漂掉
會單獨紅，而不是讓每一份 golden 因為與迴圈無關的理由全部變紅。

**golden 的內在一致性也有測試**，因為此時沒有實作可以比對：只有一個 episode id、時間不倒退、
Turn 從 1 開始不跳號、結束那筆的 `turns` 等於真的開始過的 Turn 數、任何帶 turn 的紀錄都指向
一個開始過的 Turn。

**Mutation testing（隔離 worktree，harness 先自我檢查）：** helper 永遠說相同、不比長度、
不報欄位名、回報最後一個差異 → 全紅；golden 的 turn 跳號、時間倒退、`turns` 與實際不符、
`done` 之後多一筆 observation、刪掉一整份 → 全紅。

**其中兩個我回頭單獨驗證過。** 第一輪的報告只印前兩個失敗名稱，所以看不出「名副其實的那條
測試」有沒有紅 —— 上一張票剛教過我這正是雜訊會騙人的地方。單獨重跑確認：
`test_choosing_done_does_not_produce_an_observation` 與
`test_there_is_a_golden_for_every_way_an_episode_can_end` 兩條都確實會紅。

**順帶發現一個命名問題，寫進 ticket 07 而不是在這裡改：** `config.py` 的 `max_react_steps`
用 `steps` 指的是 Turn，而它自己的描述寫的是「Hard cap on LLM **turns** per episode」。
目前沒有任何呼叫端，所以在 07 改名的成本仍然是零；等迴圈寫完就得連環境變數一起動。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **445 passed、零 skip**（400 → 445）。
