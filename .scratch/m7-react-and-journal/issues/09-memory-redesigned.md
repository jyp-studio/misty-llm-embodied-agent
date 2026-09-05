# 09 — Memory 重新設計

**What to build:** 讓機器人記得上一次互動裡發生的事，而記憶的形狀不再是三個各自變動的狀態。

**一份只增不改的 Exchange 紀錄是唯一真相**，摘要與事實是它的衍生物。取最近幾輪變成一個**純函式的切片** —— 不需要模型，微秒級可測。

**摘要與事實抽取在 Episode 邊界各做一次，不是每個 Turn 一次。** ReAct 之下一個 Episode 有多個 Turn，但使用者只說了一次話 —— 每輪抽取是在對著沒有新東西的紀錄抽，成本與延遲都白付。

**模型的訊息串不是 memory。** 那是一個 Episode 的工作脈絡，隨 Episode 丟棄；Exchange 是跨 Episode 活著的東西。這是這類系統最常見的混淆，而 `CONTEXT.md` 的 `Exchange` 定義已經明寫這件事。

這還掉 `PLAN.md` §14.6 欠的另一筆帳 —— M6 刪掉舊 runner 時帶走的 memory 折疊與持久化覆蓋。還完要在 `PLAN.md` 標記。

**不引入向量檢索。** 一個 Episode 五到十秒、一次 session 幾十輪，語料規模撐不起嵌入呼叫與額外相依的成本。

**Blocked by:** 07

**Status:** done

- [x] Exchange 紀錄只增不改，是唯一的真相來源
- [x] 取最近幾輪是純函式，不呼叫模型，可在微秒內測試
- [x] 摘要與事實抽取在 Episode 邊界各發生一次，有測試證明多個 Turn 不會讓它多跑
- [x] 有測試證明模型的訊息串不會被存成長期記憶
- [x] 持久化是一次資料 dump；重載之後事實仍在
- [x] 摘要與抽取可注入假的替身，讓結構部分的測試不需要模型
- [x] `PLAN.md` §14.6 的 memory 那一列標記為已還
- [x] 沒有引入向量檢索或外部記憶服務
- [x] 測試在專案 venv 下零 skip


## Notes（來自 #07）

- **working context 裡目前只有 trigger、模型自己的決定、Observation 和拒絕理由。** 沒有 system
  prompt、沒有 memory —— `instructions=` 參數本來寫了，但零測試零呼叫端，已按 Speculative
  Generality 移除（§15.23）。**這張票決定還該有什麼，並且要有測試。**
- `misty_agent/agent/react.py` 的 `working_context` 是 `List[Dict[str, Any]]`，交給模型時
  轉成 tuple（有測試釘住模型改不動迴圈的那份）。
- `CONTEXT.md` 的 `Exchange` **不是**模型的訊息清單：那份清單是一個 Episode 的工作脈絡、
  隨 Episode 丟掉，而 Exchange 是要活過 Episode 的。命名別混。


## Comments

完成於 2026-09-03。`misty_agent/agent/memory.py`、`tests/test_memory.py` 32 條，
`react.py` 接上 `said` 與 `memory`，`tools.py` 加 `speaks` 宣告。
全套 **844 passed、零 skip**（799 → 844）。

**三件與舊版不同的（§15.26）：**

- **折疊不刪除。** 舊 deque 溢位就 pop 掉丟給摘要，摘要漏了什麼原文就永久沒了。新版
  `_folded` 只是讀取位置，Exchange 全部留著 —— 這也讓「重載後仍在」順便涵蓋原文，不只 facts。
- **「最近幾輪」是純函式切片。** `Memory(summariser=None, extractor=None)` 也測得動，
  那是「它真的沒碰模型」最強的證明形式。§14.6 欠的五條檢查因此在微秒內跑完。
- **衍生在 Episode 邊界做一次。** 這條**只能在迴圈層級證明** —— memory 自己看不出某個 Turn
  沒有觸發它，所以 `test_a_long_episode_derives_memory_exactly_once` 跑滿八個 Turn 才斷言
  extractor 被呼叫一次。

**`close_episode()` 在 `EpisodeFinished` 之後才跑**：摘要可能是一次模型呼叫，折進 Episode
時間裡會讓每次延遲量測都包含沒人在等的工作，而且會移動四個 golden 釘住的 `episode_finished.t`。

**「說了什麼」由 Tool 宣告（§15.27）：** `@registry.tool("speak", ..., speaks="text")`，
`dispatch` 從**驗證後**的參數取值。理由與 `ends_episode` 同一條（§15.9）—— 用名字推斷的性質
會在改名那天默默失效，而 memory 會停止記錄卻沒有任何測試變紅。

**§14.6 兩筆帳都結清了**：工具參數在 #04，memory 在 #09。那張表已標記結案。

---

## Review

**兩軸沒有跑** —— 我沿用了 #07 那次 529 的推測而沒有再試（後來證明是錯的，見 §15.31），
照 §15.23 的做法自己補做。

**二十五個 mutation，第一輪存活六個**（外加一個我自己寫壞的錨點）：

- 抽取每次都看全部 Exchange（沒有測試斷言它只看最新的一筆）
- **fold 位置沒被持久化 —— 而我那條「重載不會重折」的測試是空的**：它比較兩邊的
  `as_data()["folded"]`，mutation 讓兩邊都是 0，照樣相等。改成斷言 reload 之後 summariser
  拿到的是**哪一筆** Exchange。
- 存檔不是原子的（兩個 mutation：截斷目標檔、直接寫目標檔）
- `speaks` 讀原始請求而不是驗證後的文字（沒有測前後空白）
- `speaks` 用 Tool 名字推斷（沒有「不叫 speak 但會說話」的 Tool）
- `speaks` 指向不存在的欄位也註冊得起來

補完之後 **25/25 全紅**。

**又踩到一次函式內定義參數型別的坑** —— `from __future__ import annotations` 讓註解變成字串，
函式內的類別解析不到。這是我自己在 #04 寫進 tools.py 錯誤訊息裡的那件事，這次是第三次。

**⚠️ 全套跑第一次時 `test_latency_bound.py` 紅了一次**，因為我剛跑完 mutation batteries，
load average 6.6。`PLAN.md` §14.11 已記載這條對機器負載敏感（負載下 p95 從 43 跳到 65ms）。
單獨跑通過，等負載降下來重跑全套也通過。**不是這張票造成的回歸。**
