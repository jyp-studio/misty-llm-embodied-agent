# M8 — 可執行性與 demo

Status: ready-for-agent

> 上游脈絡：`PLAN.md` §7（里程碑順序）、§4（Journal 餵三樣東西，其中一樣是「未來的
> 介面，只是另一個訂閱者」）、§8（誠實標註）、§15.1（單次 Episode，不做外層迴圈）、
> §15.24（緊急停止）、§15.29（TTS 抑制窗）。定案於 2026-09-06 的 `/grill-with-docs`。

---

## Problem Statement

M7 交付了一個完整的 ReAct agent —— 1000 條測試、四份先於實作寫成的 golden Journal、
每個決定都可追溯。**但沒有任何人可以執行它。**

具體地說：

- 沒有 `main()`，也沒有任何東西去組 `AvSession`、`AudioStream`、`DistancePipeline`、
  `EventStream`。`Session` 收的是已經建好的協作者，而沒有東西建它們。
- Journal 是這個里程碑的交付物，卻**從來沒有被寫到磁碟過** —— `JsonlFile` 造好、測過、
  零個生產呼叫端。
- 模型**不知道自己是誰**。舊主腳本的系統提示在 #12 被一起刪掉了，而 `HANDOFF.md` 當初
  訂的條件是「prompt 與 memory 搬出後才刪」—— memory 在 #09 搬了，prompt 沒有。
- `load_api_key` 同樣是造好沒接線，所以 `README` 與 `.env.example` 承諾的
  `OAI_CONFIG_LIST.json` 這條路實際上不通。

而**原本排在這裡的 M8「部署」已經沒有意義**：這個專案永遠不會有 Misty II（§1、§8），
所以 Docker 與 CI 是為一個不存在的目標做工程。

同時，這個專案最有價值的東西 —— 「每一個決定都可以指著說出它為什麼發生」—— 目前只存在於
測試斷言與 `PLAN.md` 裡。**沒有任何人可以看到它運作。**

## Solution

把 M8 從「部署」改寫成「可執行性」：讓這個 agent 第一次真的跑起來，並且讓別人看得到它在想
什麼。

三件事：

1. **一個入口。** `python -m misty_agent` 餵一個觸發輸入、跑完一次 Episode、把 Journal
   印出來。兩條路都寫：**模擬（預設）** 與真驅動（寫出來、標明從未執行過）。
2. **一個本機 demo 介面。** 執行後自動開啟瀏覽器，把 Episode 的決策過程沿時間軸展開。
   零新相依（標準庫的 `http.server`）。內建四份 golden 當範例，一打開就有東西看。
3. **把三個造好沒接線的東西接上**：系統提示、Journal 落地、`load_api_key`。

## User Stories

1. 身為一個第一次 clone 這個 repo 的人，我想執行一條指令就看到 agent 跑一次，這樣我不必讀
   完一千條測試才知道它在做什麼。
2. 身為一個沒有 Misty II 的人（也就是所有人），我想預設就跑在模擬世界上，這樣我不需要硬體
   也能執行。
3. 身為一個想知道真驅動怎麼接的人，我想看到那條路真的被寫出來，而不是留一個 TODO。
4. 身為一個讀者，我想在真驅動那條路上看到「從未在真機執行過」的明確標註，這樣我不會誤以為
   它被驗證過。
5. 身為使用者，我想餵一張照片進去，看到真的臉部偵測與距離估計，這樣我知道感知不是模擬的。
6. 身為使用者，我想餵一句文字當作使用者說的話，這樣我不需要麥克風也能觸發一次互動。
7. 身為使用者，我想（選擇性地）餵一個 wav 檔，這樣語音那條路也有呼叫端而不是又一個造好沒
   接線的東西。
8. 身為一個沒有 API key 的人，我想仍然可以看到感知的結果，這樣我至少看得到一半。
9. 身為一個沒有 API key 的人，我想打開 demo 就看到內建範例，這樣我不必先辦一個 OpenAI 帳號
   才知道這個專案在做什麼。
10. 身為一個看範例的人，我想在畫面上被明確告知「這些是規格，寫在實作之前」，這樣我不會把
    它們誤認為某一次真實執行的紀錄。
11. 身為模型，我想被告知我是誰、我有哪些能力，這樣我的決策有一個立足點。
12. 身為模型，我想被告知使用者的話來自有雜訊的語音轉錄，這樣我不會照字面理解一個明顯錯誤的
    詞。
13. 身為模型，我想被告知我只能透過 Tool 行動，這樣我不會嘗試用文字回應來「做」某件事。
14. 身為模型，我想被告知結束是我自己的選擇，這樣我知道 `done` 是一個決定而不是一個意外。
15. 身為一個維護分層主張的人，我想確認系統提示裡不含任何物理控制參數，這樣 §4 的主張在模型
    真正讀到的文字上仍然成立。
16. 身為使用者，我想預設**不要**把 Journal 寫到磁碟，這樣別人講的話不會在我沒同意的情況下
    留下逐字稿。
17. 身為使用者，我想在需要的時候用一個明確的參數把 Journal 存下來，這樣我可以留存一次執行
    的完整證據。
18. 身為研究者，我想存下來的 Journal 與 golden 是同一種格式，這樣既有的比對工具直接可用。
19. 身為使用者，我想執行 `app.py` 之後瀏覽器自己打開，這樣我不需要記一個網址或一個埠號。
20. 身為使用者，我想這個 demo 不需要安裝任何新套件，這樣「跑起來」不會變成一場相依地獄。
21. 身為一個審閱這個 repo 的人，我想看到 `requirements.txt` 沒有為了 demo 而變胖，這樣那份
    有論述的相依清單仍然成立。
22. 身為觀看者，我想沿時間軸看到每一個 Turn：模型想了多久、選了什麼 Tool、帶什麼參數、看到
    什麼，這樣「它為什麼這樣做」是可以指著看的。
23. 身為觀看者，我想看到被拒絕的 Tool 呼叫與拒絕的理由，這樣我看得到 agent 犯錯以及系統如何
    擋下來。
24. 身為觀看者，我想看到 Episode 如何結束（自己停、撞上限、被中止、出錯），這樣終止保證是
    看得見的。
25. 身為觀看者，我想在旁邊看到一個小的機器人狀態（燈色、頭的角度、手臂位置）跟著時間軸變，
    這樣抽象的 Tool 呼叫有一個具體的對應。
26. 身為觀看者，我想畫面一步步展開而不是一次全部出現，這樣我看得到決策的節奏。
27. 身為觀看者，我想可以重播，這樣我不必重跑一次（也不必再付一次錢）就能再看一遍。
28. 身為觀看者，我想展開任何一筆紀錄看到它的原始欄位，這樣「可追溯」不只是一句話。
29. 身為使用者，我想被告知這一次跑掉了多少 token，這樣我對成本有感。
30. 身為維護者，我想「畫面上顯示什麼」是被測試蓋到的，這樣它不會像 `TerminalRenderer` 那樣
    印出 `-> , 52cm away` 而沒有任何測試變紅。
31. 身為維護者，我想 demo 的 HTTP 處理是一個純函式，這樣我不需要開 socket 就能測它。
32. 身為維護者，我想 `load_api_key` 有生產呼叫端，這樣 `.env.example` 承諾的那條路是真的。
33. 身為一個讀 `PLAN.md` 的人，我想知道 M8 為什麼從「部署」變成別的，這樣里程碑的變更和其他
    決策一樣有跡可循。
34. 身為一個讀 §8 的人，我想知道那些邊界是**永遠不會**被驗證，而不是「還沒」，這樣我對這個
    專案主張的範圍不會有錯誤期待。
35. 身為 M9 的執行者，我想知道 README 裡還有哪些段落在描述已刪除的架構，這樣我不必自己重新
    找一遍。

## Implementation Decisions

### 入口

- `misty_agent/app.py` 取得一個 `main()`，可經由 `python -m misty_agent` 執行。`__main__.py`
  只做轉呼叫。
- **兩條協作者組裝路徑**：模擬（`misty_agent/fakes/` 的 `RecordingCommands` 加一個模擬世界）
  與真驅動（`RobotCommands`、`AvSession`、`RtspVideoStream`、`DistancePipeline`、
  `AudioStream`、`EventStream`）。**預設模擬。**
- 真驅動那條路必須被寫出來且有呼叫端。M7 的教訓是 `EmergencyStop` 與 `ToolContext.ears`
  造好、測到 mutation 全紅、完全沒接線，直到 #12 才發現（`PLAN.md` §15.34）。
- 所有協作者共用**同一個時鐘**（`SystemClock`），理由見 §15.34。
- `main()` 呼叫 `load_api_key()`，讓 `OAI_CONFIG_LIST.json` 這條被文件承諾的路徑真的通。
- 命令列輸入：觸發種類、使用者說的話、可選的圖片、可選的音檔、可選的 Journal 輸出路徑、
  是否啟動 demo 介面。

### 系統提示

- 放在 `misty_agent/agent/persona.py` 的模組常數。**不放 `config.py`** —— 它是內容不是可調
  參數，一段散文塞進 `Settings` 會讓那份設定變質。
- `run_episode` 取回 `instructions=` 參數。#11 移除它是因為零呼叫端零測試（§15.23）；這次
  兩者都有。
- 內容繼承舊主腳本的兩件仍然成立的事：機器人的身分，以及「語音轉錄有雜訊，不要照字面理解」。
  丟掉 JSON 輸出格式那整塊（function calling 取代了它）。加上 ReAct 才需要的：只能透過 Tool
  行動、`done` 是自己的選擇、以及分層。
- **提示中不得出現任何物理控制參數**，包括描述分層的那句話本身。初稿已對
  `layering.mentions_control_parameter` 與 `episode_invariants` 的稽核跑過。刻意不使用
  `Step` 這個詞：它是 `CONTEXT.md` 裡控制層的詞彙，教給模型等於讓模型用控制層的詞思考。

### Journal 落地

- `JsonlFile` 取得生產呼叫端，但**預設關閉**。只有明確給定輸出路徑才寫。
- 理由：Journal 含有人講的話（`tool_called` 的 `speak` 文字、Snapshot 的 `new_speech`）。
  預設把對話寫進磁碟是一個應該由使用者主動開啟的行為，而 `PLAN.md` 至今沒有任何一節談過資料
  保存 —— 悄悄開啟會是這個專案第一個沒有紀錄的決定。

### Demo 介面

- **零新相依。** 標準庫的 `http.server` 綁在 localhost，`webbrowser` 自動開啟。手寫
  HTML/CSS/JS。
- 不使用 gradio、FastAPI、Flask 或任何前端框架。相依清單是一份有論述的文件（每個被移除的
  套件都寫了理由），為了一個 demo 頁面往回加相依會讓那份論述變弱。
- **頁面重播完整的 Journal，不做串流。** Episode 跑完之後把整份 Journal 交給頁面，由頁面沿
  時間軸動畫展開。視覺結果相同（Episode 本來只有幾秒），但它讓**內建範例與真實執行走完全
  相同的路徑**，省掉一整組串流機制與其 seam。
- **Python 產出畫面資料（view model），JavaScript 只負責畫。** 每筆紀錄顯示什麼、時間軸怎麼
  排、機器人狀態怎麼變，全部在 Python 算好並被 pytest 蓋到。這是為了避免 `TerminalRenderer`
  那個 `-> , 52cm away` 的形狀：不是沒被測到，是測試蓋不到那一層。
- 版面：**決策時間軸為主**，旁邊一個小的機器人狀態圖為輔（燈色、頭部角度、手臂位置）跟著
  時間軸走。
- **內建 `tests/goldens/` 的四份當範例**，涵蓋 Episode 的四種結束方式。畫面上必須標明它們
  是**規格、寫在實作之前** —— 不得讓觀看者誤認為某次真實執行。
- 沒有 API key 時，感知仍然可以跑（mediapipe 在本機、免費），只是不會有後續決策。

### 文件

- `PLAN.md` §7：M8 改寫，並記錄它為什麼不再是「部署」。研究方向**刻意留在里程碑表外**，
  也記一句。
- `PLAN.md` §8：從「必須誠實標註的**未**驗證邊界」改寫為「**無法**驗證的邊界（本專案沒有
  硬體）」。這兩句對讀者的意思完全不同，而後者是更強也更誠實的主張。
- `PLAN.md` 新增一節記錄這次 grill 的決策。**不開 `docs/adr/`** —— 這個 repo 的決策紀錄一直
  在 `PLAN.md`，另開一處等於把紀錄拆成兩半。
- 順手修 `TerminalRenderer`：只有 `approach` 的結果帶 `result` 鍵，其餘 Tool 印出來會是
  `-> , 52cm away`。

## Testing Decisions

**好的測試斷言外部行為，不斷言實作細節。** 這個里程碑特別容易違反這一條，因為「畫面」很想用
截圖或字串比對去測。不要。測的是**畫面資料**（Python 算出來的結構），不是 HTML。

### 沿用既有 seam

- **`Session.episode`**（`tests/test_app.py`）—— 跑一次 Episode。既有的 33 條測試是 prior art。
- **`Model` protocol**（`react.py`）—— 腳本化模型，不 mock 任何 SDK。prior art：
  `tests/test_react.py::ScriptedModel`、`tests/test_llm_live.py`。
- **`RecordingCommands`**（`misty_agent/fakes/`）—— 斷言送到機器人的 HTTP 請求。prior art：
  `tests/test_drivers_contract.py`、`tests/test_direct_tools.py`。
- **`FaceDetector`** —— 真的圖片、真的 mediapipe。prior art：`tests/test_perception_face.py`
  與 `tests/fixtures/` 的兩張人臉。
- **`Journal` 的 subscriber** —— `PLAN.md` §4 早就說介面只是另一個訂閱者。

### 兩個新 seam

- **請求處理器**：純函式 `(method, path, body) → (status, headers, body)`。HTTP 的一切除了
  socket。`http.server` 的接線是薄殼，與 `main()` 同性質、同樣不測。
- **Journal → 畫面資料**：純函式，紀錄進、可序列化的顯示結構出。這是「畫面顯示什麼」的最高
  可測點。

### 必須被證明會紅的性質

- 每一種紀錄在畫面資料裡都有對應（新增一種紀錄而忘記顯示，必須變紅）。
- 被拒絕的 Tool 呼叫與理由出現在畫面資料裡。
- 四種結束方式在畫面資料裡是可分辨的。
- **系統提示不含物理控制參數** —— 用既有的 `episode_invariants` 稽核，連同九個 Tool 的
  schema 一起。
- Journal 預設不落地；給了路徑才落地；落地的格式與 golden 相同（`from_jsonl` 讀得回）。
- 沒有 API key 時感知仍可執行。
- 內建範例載入之後，畫面資料裡帶有「這是規格」的標註。

### 反向對照（negative controls）

這個 repo 反覆學到的教訓（§15.9、§15.25、§15.35）：只有一個例子的規則分不出「屬性」與
「剛好」。每一條斷言都要有一個會讓它變紅的反例，而且**併發或時序相關的測試要先證明它抓得到
那個 bug，再相信它**。

## Out of Scope

- **Docker、CI workflows、HF Spaces、gradio。** 沒有硬體就沒有部署目標。
- **外層迴圈**（「一直等使用者說話」）。§15.1 的理由未變：`AudioStream` 的轉錄與 VAD 擠在
  同一條 thread 上，是 `HANDOFF.md` §4 記著的未修缺陷。
- **`PLAN.md` §12.2 的翻轉點量測。** 有價值但不是研究成果，不該卡在前面。
- **README 中描述已刪除架構的段落**（FSM、`back_up`、`complex_task`、mermaid 圖）。M9
  本來就要重寫 README；這裡只列出清單交接。
- **沒有 key 時的腳本化模型 fallback。** 內建範例已經解決「打開就有東西看」。
- **公開網址。** 本機執行。
- **研究方向（主動發起互動）。** 刻意留在里程碑表外。

## Further Notes

- **`mediapipe==0.10.21` 的釘死是 load-bearing 的**（0.10.31 移除了 `face_mesh` API），而
  requirements 的註解說遷移到 Tasks API「排在 M5 之後」—— 那筆遷移至今沒做。本里程碑不處理，
  但任何碰到感知安裝的工作都會撞到它。
- **`docs/agents/issue-tracker.md` 說換 repo 是 M11，`PLAN.md` §7 的表寫的是 M10。** 兩者不
  一致，改寫 §7 時一併校正。
- 成本：demo 預設載入內建範例，零成本。真的跑一次視模型與 Turn 數而定，數量級是幾分錢
  （`llm_live` 套件實測 worst case 34 次呼叫約 0.09 美元）。
- `.env.example` 是受保護檔案（`HANDOFF.md` §4），本里程碑不修改。它目前有兩處過期：
  `MISTY_MAX_REACT_STEPS` 已更名、`MISTY_SPEECH_CJK_CHARS_PER_SECOND` 未列出。交給使用者。
