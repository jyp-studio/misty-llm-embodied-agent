# 12 — 刪除舊主腳本

**What to build:** 讓專案不再有第二套感知、決策與 approach 實作。

舊主腳本從 M5 起就是唯讀參考（`PLAN.md` §12.3），留著只是因為 prompt 與 memory 還沒搬出來。M7 做完之後它沒有任何理由存在 —— 而留著一份「看起來能跑但沒人維護」的完整實作，是下一個接手的人最容易誤用的東西。

**單獨一支 commit。** 那個檔案一千多行；刪除的 diff 如果混在其他改動裡，review 會看不出刪掉的是不是正確的東西。M6 #02 刪舊 runner 時就是單獨一支，那次也確實靠 review 抓到漏改的地方。

刪除後全 repo 不得留下懸空指涉。歷史分析段落（描述舊實作為什麼有缺陷）是**紀錄**，保留不動。

**Blocked by:** 09, 10, 11

**Status:** ready-for-agent

- [ ] 舊主腳本不再存在
- [ ] `grep` 找不到任何指向它的可執行指令或現況描述；只剩歷史分析段落
- [ ] 執行說明、交接文件與 README 的指涉都已更新
- [ ] `PLAN.md` §14.6 的兩筆帳都標記為已還
- [ ] 這是單獨一支 commit，不夾帶其他改動
- [ ] 全套測試在專案 venv 下綠且零 skip
- [ ] 量測台仍可一次產出兩份報告


## Notes（來自 #08）

- **`EmergencyStop` 還沒有生產呼叫端。** `misty_agent/agent/stop.py` 的機制與測試都在（15/15
  mutation 全紅），但把 `BumpSensor` 事件接到 `stop.request("foot_bumper")` 是這張票的事 ——
  舊腳本用的是 `_thread.interrupt_main()`（`full_robot_v3.py:756` 的
  `register_foot_bumper_stop`），那個做法會讓 KeyboardInterrupt 落在任何地方，而且不保證
  馬達停下來。
- 訂閱的形狀沿用舊腳本那段：`events.subscribe("BumpSensor", condition=[event_condition(
  "isContacted", "=", True)], debounce_ms=1000, keep_alive=True, ...)`。`request()` 本身
  是 idempotent 的，所以 debounce 失效也不會產生第二筆 `stop_requested`。
- 新入口要把 Journal、`ToolContext`、`EmergencyStop` 用**同一個時鐘**建起來 ——
  `run_episode` 量的延遲和 Journal 寫的時間戳必須來自同一個時鐘，否則描述的是兩次不同的執行。


## Notes（來自 07–10 補跑的 review）

- **⚠️ `EmergencyStop` 是一次性的，而且在建構時就綁死一個 Journal。** 但舊腳本的 BumpSensor
  訂閱是 `keep_alive=True`、**跨 Episode 存活**的。所以這張票不能「訂閱一次然後忘記」——
  每個 Episode 都要有自己的 `EmergencyStop`（新的 Journal、新的單次狀態），callback 必須能
  重新指向當前那一個。這件事之前沒有記在任何地方。
- **`ToolContext.ears` 同樣還沒有生產呼叫端。** `AudioStream` 已經滿足 `Ears` protocol
  （`mute_for(seconds)`），入口要把它接進 `ToolContext(ears=audio_stream)`，否則 §15.29 的
  抑制窗在真實執行時等於沒有。
- 新入口要把 Journal、`ToolContext`、`EmergencyStop`、`AudioStream` 用**同一個時鐘**建起來。
- 舊的 e-stop 是 `full_robot_v3.py:756` 的 `register_foot_bumper_stop`，用
  `_thread.interrupt_main()` —— KeyboardInterrupt 會落在任何地方，而且不保證馬達停下來。


## Notes（來自 #11）

- **`OAI_CONFIG_LIST.json` 的讀取程式只存在於 `full_robot_v3.py:81-88`**（`load_api_key()`）。
  刪掉那個檔案就等於刪掉那條路徑，而 `README.md:93` 和 `.env.example` 都還在講它。這張票要嘛
  把它搬進新入口，要嘛從 README / .env.example 拿掉 —— **兩邊都不做的話 README 會說謊**。
- **`openai` 不只 `model.py` 用**：`misty_agent/perception/asr.py:87` 也 import。刪掉舊腳本
  之後還有兩個生產消費端，兩個都是在函式內 lazy import（HANDOFF §4 要求的性質）。
- live 套件目前傳 `ears=HEARS_NOTHING`、不傳 `stop=` —— 也就是**入口接線這件事沒有任何
  live 覆蓋**，全部是這張票的。
