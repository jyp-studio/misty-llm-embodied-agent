# 07 — ReAct 迴圈

**What to build:** 一次完整的 Episode：餵一個觸發輸入進去，模型連續做幾個決定，做完之後回到閒置，過程留在 Journal 上。

這是 M7 的主菜，也是這個專案叫「agent」的理由 —— 在此之前，會呼叫控制層的只有測試與量測台。

**Turn 上限是硬上限。** `PLAN.md` §4 稱「每個 Episode 可證明回到閒置」是這個系統最強的性質，而 ReAct 化最容易弄丟它。上限值是初值，之後用 Journal 的資料修正。

**沒有獨立快路徑。** 模型在第一個 Turn 就能結束 Episode。自主終止本來就是 ReAct 的判準，硬編碼特例等於自廢武功。

**Observation = Tool 自己的結果 + Snapshot**，而 Snapshot 由迴圈附加，不由每個 Tool 各自組裝 —— 它對每個 Tool 都一樣，放進 Tool 就是複製九份。Snapshot 就三樣：主體距離、是否看得見、是否聽到新的話。序列化為 JSON 送給模型，**不並陳一份人話摘要**（同一個事實兩份拷貝會漂）。

模型呼叫走一個**窄介面**，測試注入腳本化的回應，不去 mock 第三方套件。

⚠️ **一個 M7 #03 期間發現的命名問題，在這裡最便宜地修掉：** `config.py` 的
`max_react_steps` **用 `steps` 指的是 Turn** —— 它自己的描述寫的是「Hard cap on LLM
**turns** per episode」。`CONTEXT.md` 的 `Step` 是控制層的一次驅動命令，而 `Turn` 才是
ReAct 的一輪。目前**沒有任何呼叫端**（grep 只有 `config.py` 自己），所以現在改名的成本是零；
等迴圈寫完就得連環境變數一起動。

**Blocked by:** 03, 05, 06

**Status:** done

- [x] 單次 Episode 有公開入口，接受觸發輸入、回傳結構化結果
- [x] Turn 上限是硬上限；耗盡時 Episode 仍然結束並回到閒置
- [x] 模型可以在第一個 Turn 結束 Episode，沒有硬編碼的特例路徑
- [x] Observation 由迴圈組裝：Tool 結果加上三樣 Snapshot
- [x] Observation 序列化為 JSON，不並陳人話摘要
- [x] 模型呼叫走窄介面；測試注入腳本化回應，不 mock 第三方套件
- [x] **產出的 Journal 對得上 golden 1、2、3**
- [x] 有測試證明模型收到的任何文字都不含 velocity 或 timeMs
- [x] 測試在專案 venv 下零 skip，不呼叫真模型、不需網路

## Notes（來自 #04 的 review）

- **`config.py` 的 `max_react_steps` 要改名成 Turn 的說法**（它自己的說明就寫 "Hard cap on
  LLM **turns**"）。目前零個呼叫端，現在改是免費的。
- **golden 2 的拒絕理由現在產得出來了。** #04 的 `_explain()` 原本產不出，實作已讓步，
  決定寫在 `PLAN.md` §15.7。這張票直接對檔案比就好。
- **`Dispatched` 沒有 Step 計數。** `episode_finished.steps` 是「實際發生的驅動次數的總和」，
  而 `approach` 的 Step 數目前只在 `result["steps"]` 這個字串鍵裡。迴圈要嘛用字串鍵取，
  要嘛在這張票給 `Dispatched` 加一個型別化的欄位 —— **選哪個要寫進 ticket 的 Comments**，
  因為它決定 golden 的 `steps` 是怎麼算出來的。
- `ends_episode` 從 registry 讀，**不要**比對名字（`PLAN.md` §4、§15.9）。已有兩條測試釘死。
- 被拒絕的呼叫 `ends_episode` 一定是 False，dispatch 已保證。


## Notes（來自 #05 的 review）

- **golden 2 的 `estimated_speech_ms` 現在產得出來了。** `speak` 回傳它，
  `estimate_speech_ms("Coming over.", Settings())` = 1409，與 golden 逐位相符。速率常數在
  `Settings` 裡並標 UNCALIBRATED（§15.13）。
- **`max_react_steps` 的值也要決定，不只是改名。** 舊腳本揮一次手是 5 個 Turn，而預設上限
  就是 5 —— §4 的「表現力靠組合」在這個上限下付不起。§15.15 記了這件事並指名由這張票決定，
  **要有依據，不是挑一個更大的數字**。
- `look_around` 找到人之後**頭會停在那裡**，所以這張票附加的 Snapshot 才會是關於那個人的
  （§15.14）。不要在 Tool 回傳之後把頭轉回正。
- Tool 的結果**不重複參數**：`display_image` / `play_audio` 只回 `{"ok": True}`，模型送了
  什麼在 `tool_called.args` 上。§15.4。


## Comments

完成於 2026-09-03。`misty_agent/agent/react.py`（迴圈與窄介面）、`tests/test_react.py`
38 條測試。全套 **776 passed、零 skip**（730 → 776）。

**三個 golden 都對上了** —— 逐紀錄、逐欄位。包含 ticket 04 讓步產出的拒絕理由
（`"pitch 140 is outside the permitted range"`）和 ticket 05 的 `estimated_speech_ms: 1409`，
兩個都是在那些實作存在**之前**寫進 golden 的數字。

**四個決定，都記在 PLAN：**

- **§15.19 `max_react_steps` → `max_turns_per_episode`，值從 5 改成 8。** 下界是推導的：
  舊腳本 `_do_gesture("wave")` 展開成 6 個原始命令（機械數過：body 2×2 + reset 2），
  §4 說那種表現力由組合取代，那上限至少要容得下它再加一句話和一次自我結束 = 8。
  代價是 golden 3 跟著長到 8 個 Turn。
- **§15.20 Step 計數放 `Dispatched` 上**，不讓迴圈去撈 `result["steps"]`。字串只在
  `STEPS_KEY` 一處，`_steps_in()` 拒絕負數、布林和非整數 —— `steps: True` 會悄悄變成 1。
- **§15.21 golden 的 `t` 讓步。** 手寫的 2ms/4ms 簿記成本在注入時鐘下一律是 0（那個時鐘
  只在 `sleep()` 時前進，而 dispatch 不 sleep）。新規則：**時間只在真的有等待時前進**，
  所以每個 `t` 仍可用檔案自己的 `latency_ms` 手算驗證。這削弱了 spec 的「逐字元比對」說法，
  §15.21 把能主張的範圍改寫清楚了。
- **§15.22 golden 3 的 `look_around` 結果讓 §15.14 贏**，加上 `found_at_yaw`。

**golden 改動逐欄位盤點過**：goldens 1、2 只有 `t` 變，golden 3 是 `t` + `found_at_yaw` +
延長，golden 4 沒動。**沒有夾帶內容修改。** 把原始 golden 放回去跑 ticket 03 的六十條內容
斷言：59 條通過，唯一失敗的正是那條專門防「改上限默默失效」的測試。

---

## Review

**兩軸這次跑不起來** —— subagent 連續四次 529。兩軸的工作我自己補做，而且這件事記在
`PLAN.md` §15.23，因為前六張票每一張都是 review 抓到我自己看不到的東西。

自己跑的十三個 mutation（刻意挑第一輪沒想到的）**存活六個**，全是真漏洞。共同原因一句話：
**我的斷言幾乎全指著 Journal，而 Journal 可以是對的、同時模型什麼有用的資訊都沒收到。**

最嚴重的是 `as_text` 回傳 `""` 就存活 —— 分層測試（模型收到的文字不含 velocity/timeMs）
整個建在它上面，它回空字串那條測試在任何實作下都會綠。其他五個：Snapshot 的值沒被斷言真的
到得了模型、模型看不到自己上一輪的要求、trigger 沒進 context、working context 以可變 list
交出去。補了九條指著 working context 的測試，12/13 紅。

剩下那一個（寫第二筆 `EpisodeFinished`）**是實測驗證過的等價變異** —— `Journal.record`
本來就拒絕。§15.17 的教訓是「宣稱等價要實測」，這次照做了。

**`instructions=` 移除**：接線了但零測試零呼叫端，ticket 09 才是決定 working context 裡還該
有什麼的那張票。

**⚠️ `.env.example` 過期兩層** —— `MISTY_MAX_REACT_STEPS` 還在「DECLARED BUT NOT YET
WIRED」區塊裡，而迴圈已落地、名字也改了。它是四個受保護檔案之一，**只標記不修改**。
