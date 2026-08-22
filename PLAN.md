# PLAN — misty-embodied-agent 重構

> 取代舊的 `HANDOFF.md`（已刪除，副本在 `~/dev/misty-embodied-agent.backup/`）。
> 本文件是 grilling 後的定案共識，給沒有前文脈絡的新對話看的，內容自足。
> 定案日期：2026-08-09 · 分支：`refactor/react-agent`

---

## 0. 一句話

把一個課堂專案（LLM 驅動的 Misty II 具身 agent）重構成**完整的 ReAct agent**，移除第三方 code-gen 框架、重寫驅動層取得乾淨授權、建立無硬體的重放測試台證明並修正感知延遲缺陷，最後以 Docker + CI/CD 交付。

**這是履歷作品，不是可上線的機器人系統。** 所有未經實機驗證的部分都必須誠實標註。

---

## 1. 前提（不可協商）

| 項目 | 定案 |
|---|---|
| 交付定位 | 履歷作品：完整 ReAct agent + Docker + CI/CD |
| 硬體 | **永久無實機**。`approach_user()` 與 public `approach()` 都從未在真機執行過 |
| 下游使用者 | 假設無人拿真機跑；但校正參數必須可從 config 調整 |
| 預算 | 大。開發直接呼叫真 LLM API，離線錄放測試暫不做（保留為 later） |
| README | **最後才重寫**，不是重點 |
| 工作方式 | 只改本地 `/Users/jyp/dev/misty-embodied-agent`，不動 GitHub |

**不要提出任何需要碰硬體的方案**（包括「借 30 分鐘錄 trace」——已排除）。

---

## 2. 架構決定

### 移除
`Agents/`（14 檔 / 8512 行）、`AutoMisty.py`、`complex_task` 欄位與整條程式碼生成路徑。
依賴移除：`pyautogen`、`langchain-openai`、`langchain-core`、`langchain-community`、`openai-whisper`（連帶 torch）。

> 主程式對 AutoMisty 的接觸面只有兩處：`full_robot_v3.py:41` 的 import 與 `:800` 的呼叫。這是切除，不是重構。

### 移到 `legacy/`（不刪，加 `.gitignore`）
`Mistydemo/`（932K，上游展示素材）、`code/mistyPy/`（AutoMisty 的 sandbox cwd）。
→ `CUBS_Misty.py` 的副本數從 **6 份（4 種不同 hash，已分歧）** 降為 1 份。

### 保留
`RobotCommands.py` —— **Misty Robotics 官方 Python SDK 的自動產生檔**（`GenerateRobot.py` 產出，205 個方法，docstring 全是 `docs.mistyrobotics.com` 連結），**Apache-2.0**。加上來源標頭即可合法保留。

### 重寫
`CUBS_Misty.py` 的 `Robot(RobotCommands)` 類別（AutoMisty 在官方 SDK 上加的那一層）。
主程式對它的依賴只有 10 個符號（其中 4 個是私有的，本身就是設計異味），拆成四個子系統：

| 子系統 | 現況符號 | 新位置 |
|---|---|---|
| 視訊 | `start_av_stream` / `stop_av_streaming` / `_video_reader_thread` / `frame_queue` | `drivers/av_stream.py` |
| 音訊 | `_read_audio_stream` / `_process_audio` / `is_silent` / `transcript_queue` | `drivers/audio_stream.py` |
| 事件 | `register_event`（websocket，foot-bumper e-stop） | `drivers/events.py` |
| 基底 | `class Robot(RobotCommands)` | `drivers/robot_commands.py`（保留） |
| ~~Whisper~~ | `load_whisper_model` | **移除**，改 API 轉錄 |

實際重寫量約 200–300 行。

### 目標結構

```
misty_agent/
├── config.py                 # pydantic-settings：全範圍常數 + 跨欄位 validator
├── drivers/
│   ├── robot_commands.py     # Apache-2.0 官方 SDK（保留 + 來源標頭）
│   ├── av_stream.py          # 重寫：RTSP → frame_queue（擷取時打時間戳）
│   ├── audio_stream.py       # 重寫：音訊 → ASR adapter
│   └── events.py             # 重寫：websocket（bumper e-stop）
├── perception/
│   ├── face.py               # MediaPipe 臉部 / 距離估計
│   └── asr.py                # ASR adapter（API 為預設，介面保留可切換）
├── agent/
│   ├── events.py             # 事件型別 + EventBus
│   ├── react.py              # ReAct 迴圈
│   ├── tools.py              # 工具 schema + dispatch（註冊表模式）
│   └── memory.py             # 三層記憶（現有邏輯搬移）
├── control/
│   └── approach.py           # 確定性閉環，LLM 不碰物理參數
└── fakes/fake_robot.py
harness/                      # 合成影格 replay（= 展示品 + 缺陷 A 的證明）
tests/
legacy/                       # 舊 AutoMisty 素材
```

**Python 3.11**（mediapipe wheel 支援最穩，pin 時再確認）。
**Docker** `python:3.11-slim`，multi-stage、非 root user、base image digest 釘死。

---

## 3. 授權

現況問題：repo 唯一的 `LICENSE` 是 **Academic Research License，著作權人是 AutoMisty 作者（Xiao Wang 等人）**，且 README 聲明原創元件也採同樣條款——等於使用者自己寫的主控迴圈、記憶系統、閉環控制器全被綁住。

處置：

1. **刪除**現有 `LICENSE`（移除 AutoMisty 元件後已不適用於任何東西）
2. 全 repo 改 **Apache-2.0**（與唯一保留的第三方檔案同授權，單一授權 repo）
3. 新增 `NOTICE`，標示 `RobotCommands.py` 來自 Misty Robotics Python SDK (Apache-2.0)，並標示修改
4. `RobotCommands.py` 檔頭加來源與授權標頭

> ⚠️ **M1 → M3 之間是過渡狀態**：`CUBS_Misty.py`（AutoMisty 衍生）在 M3 前仍留在樹裡，
> 所以 repo **尚未**完全 Apache-2.0。原授權全文保留於 `legacy/LICENSE.AutoMisty`，
> `NOTICE` 明確列出「已移除」與「仍存在」兩份清單。**M3 完成時必須更新 `NOTICE`。**
>
> 著作權人：`Chieh-Yu Pan`（`LICENSE` 與 `NOTICE` 兩處）。

**工具描述必須自己寫。** AutoMisty paper 的「136 個 optimized APIs 加完整文件」實體在 `Agents/MistyActionAgent.py`(92K) 與 `MistyPerceptionAgent.py`(96K) 的 prompt 裡，在他們的授權底下。來源改用官方 `docs.mistyrobotics.com`（照官方文件寫參數語意是照抄事實，不是抄他們的文字）。

> `CUBS_Misty.py:24` 有一行 `sys.path.append("/Users/xiaowang/Documents/AutoMisty/...")`；`:22,25` 是壞的自我 import（`from RobotCommands import RobotCommands` 三行後被 `from CUBS_Misty import RobotCommands` 蓋掉）。
> **明確延後到 M3**（M2 code review 指出這條原本掛在 M1 底下）：該檔案在 M3 會被整個取代，現在編輯它是白工，而且它在 M3 前仍受上游授權管轄——改動別人授權下的檔案只為刪三行沒有意義。

---

## 4. ReAct 設計

### 機制
- **OpenAI function calling**（模型端保證結構，天然提供 `tool` role 的 observation 回填位置）
- 工具集 **12 個左右**，註冊表模式（decorator 註冊），加工具 = 一個函式 + 一份 schema，不動 `react.py`
- `MAX_REACT_STEPS = 5` —— **初值，用事件流量測後修正**
- **無獨立快路徑**：LLM 第一輪就能輸出 `done`（自主終止本來就是 ReAct 判準之一，硬編碼特例等於自廢武功）
- **必須保留 step cap**：目前系統最強的性質是「每個 episode 可證明回到 IDLE」，ReAct 化最容易弄丟這個

### 分層開放（工具集邊界）
```
直接開放（加參數 clamp）：display_image(表情) / move_arms / move_head /
                          change_led / play_audio / speak / look_around
高階意圖（走確定性閉環）：approach / back_up      ← LLM 不碰 velocity / timeMs
終止：                    done
```

**分層原則是硬的**：LLM 決定「要不要接近、失敗了改做什麼」，控制層決定「這一步走幾公分」。
讓 LLM 直接算「速度 × 時間」正是 README 開頭批判的事，也是專案最站得住腳的設計主張。

AutoMisty 移除後的表現力由**組合**取代：一支舞 = LLM 在多個 ReAct step 裡組合 `move_arms` + `change_led` + `play_audio`。比 code-gen 更好——有界、可觀測、不執行任意 Python、每步都有 observation。

### Observation 的組成
每步 observation = **動作結果 + 便宜的感知快照**：
```jsonc
{"result": "arrived", "distance_cm": 63,
 "face_present": true, "new_speech": null}
```
距離、臉在不在、transcript queue 有無新句子——**三樣都已經在跑，零額外 LLM 呼叫、零額外延遲**。
不做每步重跑 VLM（每步 +1–2 秒，而 5–10 秒的 episode 內場景幾乎不變）。

**連帶必須處理**：目前 ACT 期間整段 `perception.pause()`，新語音進不來。要把抑制範圍縮小到**只在 TTS 播放期間**（用 `speak` 回傳的 `spoken_ms` 當抑制窗）。可在 harness 測：餵「機器人講話期間使用者插話」情境，斷言插話有收到、自己的話沒有。

### 結構化事件流（`agent/events.py`）
每件值得記錄的事發出有型別的紀錄，終端機輸出退化成其中一個渲染器：
```jsonl
{"t":12.34,"type":"llm_call","step":1,"latency_ms":1840,"tokens":{"in":1203,"out":47}}
{"t":14.18,"type":"tool_call","step":1,"tool":"approach","args":{}}
{"t":19.02,"type":"observation","step":1,"result":"arrived","distance_cm":63}
{"t":19.90,"type":"episode_done","steps":2,"total_latency_ms":5600}
```
一個模組同時餵養三件已決定要做的事：LLM 決策測試的斷言標的、延遲與步數量測、未來 web UI（只是另一個訂閱者，agent code 一行不改）。

---

## 5. 已確認的缺陷與處置

以下皆為**已驗證**，非猜測。

### A. 閉環實際上是開環——距離讀數是過期的（最嚴重）
- **A1** `frame_queue` 無界（`CUBS_Misty.py:115`），producer 每幀 put 只 sleep 10ms（`:323`），consumer 每幀跑 MediaPipe（30–50ms，`full_robot_v3.py:292`）→ **queue 單調成長 + 記憶體單調成長**
  > ⚠️ **「30–50ms」已被實測推翻：3.81ms。** consumer 其實比 producer 快近十倍，
  > 在這台機器上 queue 不會積。缺陷仍在（管線沒有背壓），但宣稱範圍要改。見 §12.2。
- **A2** 時間戳蓋在「處理當下」而非「擷取當下」（`full_robot_v3.py:299`）→ `get_distance(max_age_sec=2.0)` 的 age filter **在檢查錯的東西**：只保證「2 秒內算出來」，不保證「2 秒內拍的」
- **A3** 移動後沒作廢舊樣本：`_flush()`（`:264`）清了 `frame_queue`/`transcript_queue`/`visual_events`/`audio_events`，**獨漏 `_distance_samples`**；而 `deque(maxlen=9)` 的中位數會被移動前樣本主導

**修法**：consumer 只處理最新幀（drain 到空取最後一張，或 `maxsize=1` 丟舊）+ 時間戳在擷取時打上並隨幀傳遞 + `approach` 每步後清 `_distance_samples` 並等 ≥2 筆新樣本。

> ⚠️ 這是**正確性**問題，不是效能問題。**不做效能最佳化**（不調 MediaPipe 參數、不換模型），只修正時間語意。

> 現有測試抓不到的原因：`test_sim.py` 的 `FakePerception.get_distance()` 直接回傳世界瞬時真值加雜訊——零延遲、零積壓，等於把要測的東西假設掉了。

### B. `MIN_SAFE_DISTANCE_CM` 是 dead code
已窮舉驗證：進入 `direction > 0` 需 `delta > 12` 即 `d > 72`，此時 `max_forward = d − 45 > 27` 恆成立 → `full_robot_v3.py:714-717` 分支不可達，clamp 從未生效。真正防撞的是 0.7 gain。
且它 clamp 的是**命令距離**而非**實際行走距離**，擋不住校準誤差超衝（實速為校準值 2 倍時模擬會突破 45cm 至 44.0）。

**M2 更新——原本「config 化後它不再是死碼」的預測，被 M2 的一個設計選擇擋掉了（不是原分析算錯）。** `config.py` 的 validator 要求
`target − tolerance > min_safe`，而該分支可達需要 `min_safe > target + tolerance`；兩者相加得
`tolerance < 0`，與欄位約束矛盾。**所以那個 runtime guard 對任何合法 config 都不可達**——
不是「在預設值下是死碼」，是**由構造保證的死碼**。已由 `tests/test_step_policy.py` 的組合掃描證明。

措辭上要誠實：**guard 不可達是因為 M2 選了那條 validator**，不是因為原本的分析有誤。沒有那條 validator，config 化確實會讓它復活。這是一個設計決定，不是一個發現。

而這個決定是好的：不變量提前到 config 載入時強制，比在執行期擺一個永不觸發的 guard 假裝有防護強。

→ **M5 的工作因此改變**：不是「讓 guard 活起來」，而是
①把 guard 改成明示的不可達斷言（或移除並在註解指向 validator），
②**真正要解的是「clamp 命令距離 ≠ clamp 實際距離」**——validator 完全沒碰這個，校準誤差仍會讓機器人衝過 45cm。這才是缺陷 B 的實質。

**M5 更新——已在明示假設內修復。** `max_actual_motion_multiplier=2.0` 明列為
UNCALIBRATED 假設；`plan_step()` 先算 gain/min/max 偏好，再把前進與後退命令限制在
「最大單調實際位移仍不得穿過抵達帶遠端」的距離。前進另保留 safety-floor cap；合法
config 下抵達帶 cap 更嚴格。M4 的 100→44cm 反例現在經 public `approach()` 於 2× 情境
停在抵達帶內且不低於 45cm。這不是實機安全認證：超過倍率、非單調瞬間超衝、距離尺度
誤差與未掃描的 transport lag 都仍未知，見 §13 與 M5 證據報告。

### C. `max(8.0, ...)` 是 dead code 兼未爆彈
`full_robot_v3.py:706`：`abs(delta) > 12` ⟹ `abs(delta)×0.7 > 8.4 > 8`，下限永不生效。
但 `DISTANCE_TOLERANCE_CM` 一旦調到 11 以下就會活過來，而**後退方向完全沒有 clamp** → 後退超衝 → 來回震盪至 step cap。
→ **實作 + 補後退方向的 clamp**。

**M5 更新——已修復。** `min_step_cm` 改成偏好下限，正式 arrival-band cap 在兩個方向
都優先於它；非預設 tolerance、gain、min-step 已經由 public `approach()` 外部行為測試
驗證不會強迫跨帶或可預見地往返震盪。Runtime、reachability、sweep 與測試都走同一個
`plan_step()`，沒有第二份控制公式。

### D. 動作回傳值被完全丟棄
`approach_user()` 回傳 `arrived`/`lost_user`/`timeout`/`drive_error`，`full_robot_v3.py:784` 直接丟掉，memory 也沒記錄。
→ **在重寫後自動消失**：工具層本來就回傳結構化結果並寫回 memory。

### E. 第一輪就放棄
`full_robot_v3.py:693`：`get_distance` 需 ≥2 筆樣本，剛 `pause()` 完常不足 → 第一輪直接 `return "lost_user"`，零重試。
→ 先 poll 1–2 秒再判定。

---

## 6. 測試與驗證策略

### replay harness（`harness/`）—— 專案中軸
**一份工作交付四件事**：可跑的 demo、缺陷 A 的證明、ReAct 的 observation 來源、CI 能跑的東西。

**影格來源**：CC0 授權人臉圖 + 程式按已知比例縮放貼到畫布。
→ MediaPipe **真的偵測得到**（耗時真實發生）+ 真值距離**精確已知** + 完全可重現 + 零外部素材。
（純合成色塊 MediaPipe 偵測不到；繞過 MediaPipe 則把主因假設掉，重蹈 `test_sim.py` 的錯。）

**主斷言**：`get_distance()` 讀數落後真值的秒數（互相關估計），p95。
**門檻先量再定**——先跑一次量出現況，再訂在「修好後實測值 × 安全係數」。
**修復前必須是紅的**（先證明缺陷存在，再修），否則等於沒證明。

**診斷指標**（不掛門檻）：queue 深度上界、幀齡 p95。

### 可量測 vs 不可量測的分界
```
[真值] ─ 相機曝光 → Misty 編碼 → RTSP over WiFi ─▶ [進 process] ─ put/queue/MediaPipe/deque ─▶ [get_distance()]
        └────────── 截段 A：需要硬體，量不到 ──────┘  └──────── 截段 B：100% 在 Python 裡，可精確量測 ────┘
```
**缺陷 A1/A2/A3 全部在截段 B。** harness 注入影格的位置正是 RTSP 交付的位置。
截段 A → `SENSOR_TRANSPORT_LAG_S` config 參數，標 `# UNCALIBRATED`，並用它做**參數掃描畫出控制律的魯棒邊界**（比單點數字更有說服力，且是無硬體下能做出的最強結果）。

### LLM 決策測試
**不變量斷言**（斷言事件流），非金標準文字比對：
- 「這個情境必須在 ≤3 步內 `done`」
- 「第一步必須是 `speak` 而非 `approach`」
- 「使用者說『別過來』時，整個 episode 不得出現 `approach`」

不會因 GPT-4o 換句話說而變紅。

### 其他
- ~~`test_sim.py` → **遷移到 pytest**~~ —— **已撤回。** 實際盤點後改為整個刪除，不遷移；理由與逐項下落見 §14.3 與 `docs/measurements/m6-coverage-audit.md`。（順帶更正：那個 runner 是 24 個檢查不是 28 —— 28 是 M1 移除 AutoMisty 之前的數字。）
- 驅動層 → **契約測試**：對照官方 REST/WebSocket 文件驗證送出的 HTTP 請求格式。**證明請求格式正確，不證明機器人會照做**——這條線寫進 README
- `FakeRobot.__getattr__` 對未定義方法回 noop，等於假設所有 API 呼叫成功 → `drive_error` 路徑從未被執行，需補錯誤注入

### CI（`.github/workflows/`）
- **每個 push**：`ruff` + `pytest` + `docker build`
- **不加 mypy**（codebase 大量動態屬性，投報率低，等主體穩了再說）
- **真 LLM 測試** → `workflow_dispatch` 手動觸發，**不擋 merge**
  （CI 必須免費、確定性；一個會因為模型心情變紅的 CI 等於沒有 CI）
- 離線錄放（把手動 workflow 的輸出存成 fixture）保留為 later，不是現在

---

## 7. 執行順序

> **順序更正**：原 `HANDOFF` 的 `D → A → ReAct` 建立在「修補現有 code」的假設上。改成重寫後缺陷 D 自動消失，實際順序如下。

| | 里程碑 | 產出 |
|---|---|---|
| **M0** | 安全網 | 目錄備份至 `~/dev/misty-embodied-agent.backup`；分支 `refactor/react-agent` ✅ |
| **M1** | 清理與授權 | 移除 `Agents/`+`AutoMisty.py`；`Mistydemo/`+`code/mistyPy/` → `legacy/`；Apache-2.0 + NOTICE + 檔頭；requirements 部分瘦身 ✅ |
| **M2** | config | `pydantic-settings`，全範圍常數 + `SENSOR_TRANSPORT_LAG_S` + 跨欄位 validator ✅ |
| **M2.5** | code review | 兩軸 review（Standards / Spec）+ 修正，見 §10 ✅ |
| **M3** | 驅動層重寫 | `drivers/` 四件；**擷取時打時間戳**（缺陷 A2 的地基）；契約測試 ✅ 見 §11 |
| **M4** | harness | 合成影格 + 真值軌跡 + 延遲量測。**任務已改**，見 §12 ✅ |
| **M5** | 重寫感知→控制管線 | latest-value 距離管線 + fresh post-move readings + bounded public `approach()` + 條件式安全與 M5 證據，見 §13 ✅ |
| **M6** | 測試套件收斂 | 覆蓋盤點 + 刪除 `test_sim.py` + 距離相依噪音 Sweep，見 §14 |
| **M7** | ReAct + Journal | `journal.py`（schema 先於實作）+ `tools.py`（12 工具，註冊表）+ `react.py`（step cap / 感知快照 / TTS 抑制窗）**＋ §14.6 的重建清單** |
| **M8** | 部署 | Docker multi-stage + CI workflows |
| **M9** | 文件 | README 與架構圖重寫 |
| **M10** | 收尾 | 開新 repo，乾淨歷史匯入 |

---

## 8. 必須誠實標註的未驗證邊界（寫進 README）

- 驅動層 HTTP / WebSocket 請求格式 —— 只有契約測試，**無實機驗證**
- `CM_PER_SEC_AT_PERCENT`（實際驅動速度）
- `MAX_ACTUAL_MOTION_MULTIPLIER`（一次命令中的最大單調實際位移倍率；預設 2× 只是模擬假設）
- `FOCAL_LENGTH`（相機焦距常數）
- `SENSOR_TRANSPORT_LAG_S`（相機→process 的傳輸延遲）
- 馬達 deadband（20% 會不會根本不動）
- RTSP 端到端延遲的真實數量級
- ASR 在 Misty 麥克風 + 環境噪音下的辨識率
- `drive_time` 執行中再下指令的實際行為
- **`approach_user()` 與 public `approach()` 都從未在真機執行過**（公開 demo 的 planner 輸出是 `movement: "stay"`）

處理原則：不試圖「測」這些，而是 ①隔離成明確標註的校正參數，②用參數掃描證明控制律對其誤差的魯棒範圍，③在 README 誠實區分**已模擬驗證** vs **未實機驗證**。

---

## 9. 環境備註

- 專案路徑 `/Users/jyp/dev/misty-embodied-agent`（**不是** `FocusCompany`）
- 備份 `/Users/jyp/dev/misty-embodied-agent.backup`（含刪除前的 `HANDOFF.md`）
- 只改本地，**不動 GitHub**；`origin/main` 維持原狀直到 M11

---

## 10. M2.5 — code review 的結果

用 mattpocock `code-review`（Standards + Spec 兩軸，平行 sub-agent）審 `e0bfa37...HEAD`。
repo 無自訂規範文件，故 Standards 軸只適用 Fowler smell baseline，**零硬性違規**。

### 已修

| # | 軸 | 問題 | 處置 |
|---|---|---|---|
| 1 | Spec (c) | **`forward_clamp_is_reachable` 對合法 config 回答錯誤。** 閉式解只模型化 gain 項，漏了 `min_step_cm` 會把命令步長抬高。反例 `min_step_cm=30`：d=73 時命令 30cm 對上 headroom 28cm，clamp 確實生效，但屬性回 `False`。 | Reachability 改為**掃描真實的 `plan_step`**，不再用手推閉式解。M5 的對稱控制律沿用同一原則，現由 `test_arrival_bound_reachability_accounts_for_the_min_step_floor` 回歸。 |
| 2 | Standards #4 | **控制律在測試裡被手抄一份**，真實控制律改變時副本會默默分歧而測試照樣綠。 | 抽出 `misty_agent/control/step_policy.py`，`plan_step()` 成為唯一實作，三個消費者（`approach_user`、reachability 分析、測試）共用。 |
| 3 | Spec (b) | reachability 分析寫在 `config.py` 裡是 scope creep，且分層不對。 | 移到 `control/step_policy.py`。`config.py` 現在只有資料與不變量。 |
| 4 | Spec (a) | `llm_temperature` 宣告了卻沒接線；`TRIGGER_COOLDOWN=3.0` 與記憶呼叫的 `temperature=0.2/0.0` 仍是字面值。**宣告了卻沒接線比字面值更糟——它看起來可調，實際不可調。** | 全部接線，並新增 `memory_summary_temperature` / `memory_fact_temperature` / `trigger_cooldown_s`。 |
| 5 | Standards #1 | `.env.example` 把 `MISTY_MAX_REACT_STEPS` 當成能用的東西宣傳。 | 獨立成「DECLARED BUT NOT YET WIRED」區塊並註解掉，標明各自落在哪個里程碑。 |
| 6 | Spec (a) | `CUBS_Misty.py` 的三行清理掛在 §3（M1），但沒做。 | §3 改為**明確延後到 M3** 並寫出理由。 |
| 7 | Spec | §5-B 的「原本的推論是錯的」把一個設計選擇說成發現。 | 改寫成「被 M2 的一個設計選擇擋掉了（不是原分析算錯）」。 |

### 已知未修（刻意）

- **Middle Man / Shotgun Surgery**：`full_robot_v3.py` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派，留下同一份資料的兩條存取路徑。**刻意保留**——`full_robot_v3.py` 會在 M3–M8 被拆進 `misty_agent/`，屆時整個區塊消失。現在改只是把同一份工作做兩次。
- **Data Clumps**：控制律欄位仍在 frozen `Settings` 中一起旅行。M5 刻意用窄的 `StepPolicyConfig` protocol 隔離依賴，沒有再引入一層 `ApproachPolicy` 公開模型；理由見 §13.3。
- **import 時凍結的預設值**：`get_distance(max_age_sec=settings.distance_max_age_s)` 在 import 時綁定。`settings` 是 frozen 且 process-global，目前無害。

### 尚未做的另一軸

**內建 `/code-review` 沒跑過。** 它找的是正確性 bug（失敗情境、崩潰、邏輯錯誤），與上面兩軸完全不重疊。這是 M3 開始前建議補的一步——而且它是**使用者手動觸發**的，agent 不能代跑。

---

## 11. M3 — 驅動層重寫的結果

用 mattpocock `codebase-design` 的詞彙做的：舊的 `Robot(RobotCommands)` 是教科書級的
**shallow module**——呼叫端要知道 10 個符號（4 個私有）**外加 5 條順序規則**：清
`_stop_event` → `start_av_stream()` → 手動開三條 thread 指向私有方法 → 自己排乾兩個
不屬於它的 queue → 設 `_stop_event` + `stop_av_streaming()`。呼叫端等於把模組的
lifecycle 重寫了一遍。

現在的介面：

| 模組 | 介面 | 藏在後面的 |
|---|---|---|
| `AvSession` | `open` / `close` / `url` | reset→enable→start 三步、錯誤處理、URL 組裝 |
| `RtspVideoStream` | `start` / `stop` / `read` / `flush` / `backlog` | reader thread、cv2、旋轉、**擷取時打時間戳** |
| `AudioStream` | `start` / `stop` / `read` / `flush` / `mute_for` | 兩條 thread、PyAV demux、VAD、轉錄 |
| `EventStream` | `subscribe` / `close` | websocket、訂閱訊息、死連線回收（原本 6 個公開方法） |
| `Transcriber` | `transcribe` | 一個方法的 port，OpenAI adapter |

`full_robot_v3.py` 現在**一條 thread 都不開給驅動層**，也不碰任何 queue。

### 過程中發現的既有缺陷（都是「真機會安靜地不理你」那種）

| # | 缺陷 | 處置 |
|---|---|---|
| 1 | **AV reset 打的是不存在的端點**。`_force_kill_av_services` 手寫 POST 到 `/api/avstreaming/disable` 與 `/api/audio/recording/stop`，REST reference 裡兩條都沒有；官方是 `services/avstreaming/disable` 與 `audio/record/stop`。原本那個 reset 極可能一直是 404。 | 移進 `AvSession._reset()`，改用 SDK 方法。契約測試 `test_reset_uses_the_documented_endpoints` 釘住。 |
| 2 | **websocket 訂閱訊息不是 JSON**。`self.ws.send(str(self.get_subscribe_message()))` 送的是 Python dict 的 `str()`——單引號、`True` 而非 `true`。unsubscribe 那條倒是正確用了 `json.dumps`。 | 一律 `json.dumps`。回歸測試 `test_subscribe_frames_serialise_as_json`。 |
| 3 | **websocket callback 用的是 0.58 以前的簽名**。`on_message(self, message)` 少了 `ws` 參數，而 `requirements.txt` 沒 pin `websocket-client` → 裝到的一定是新版 → `TypeError`。**foot-bumper e-stop 很可能從來沒有真的接上過。** | 改用現行簽名。 |
| 4 | **音訊 buffer 無界成長**。`audio_buffer` 只在「utterance 結束」時清空，機器人閒置時沒有 utterance 會結束 → 從 process 啟動開始一路 concat；而且每段轉錄都夾帶前面所有靜音。這是 A1 的兄弟，只是在音訊側。 | `UtteranceDetector` 改成沒在講話時只留 `audio_preroll_s` 的 pre-roll。測試 `test_idle_audio_is_bounded_by_the_preroll`。 |
| 5 | `CUBS_Misty` 的 `speak` / `move_arms` / `move_head` **官方 SDK 本來就有**（`robot_commands.py:762,1547,1562`），那三個只是加長 docstring 的重新宣告。唯一的原創行為是 `speak` 順手設 `ignore_transcript_until`。 | 直接用 SDK 的；TTS 抑制窗變成 `AudioStream.mute_for()`，語意乾淨且 M8 要縮小抑制範圍時就改這一個地方。 |

### 與計畫的偏離（三處，都是刻意的）

1. **缺陷 A1 的修法換了位置。** §5 寫「consumer 只處理最新幀」。但 queue 現在藏在
   `read()` 後面，M5 只要改 `RtspVideoStream` 一處，consumer 一行都不用動。修法不變，
   位置從呼叫端移到 seam 後面——這正是把它做成 deep module 換來的 locality。

2. **`min_utterance_s` 的判定基準變了。** 舊碼拿「buffer 全長」比 0.3 秒，而 buffer 含
   啟動以來的所有靜音，所以那個門檻幾乎永遠通過（缺陷 4 的副作用）。現在 buffer 有界，
   門檻才真的在擋短音。**這會改變行為**：以前放行的極短哼聲現在會被丟掉。這是原意。

3. **不再重新取樣。** 舊碼用 librosa 把 44.1 kHz 降到 16 kHz 餵 Whisper，**沒有低通濾波**
   → 混疊。hosted API 吃原生取樣率，所以整段拿掉，順帶少一個相依。

### 授權

`CUBS_Misty.py` 已刪除，`NOTICE` 改為「AutoMisty 衍生程式碼已全部移除」。
**repo 現在整個是 Apache-2.0。** `requirements.txt` 的過渡區塊清空
（`openai-whisper`+torch、`langchain-*`、`librosa`、`pynput`）。

### 一併處理掉的 §6 待辦

`FakeRobot.__getattr__` 對所有呼叫回 noop、錯誤路徑從沒執行過 →
`misty_agent/fakes/fake_robot.py` 的 `RecordingCommands` 有 `fail_endpoints`，
契約測試已用它跑過 `AvSession` 的兩條失敗分支。同一個類別同時是 mock mode 的機器人，
所以「無硬體時跑的東西」與「測試涵蓋的東西」不會分岔。

### 行為變更：mock mode 改為顯式

以前是「`import CUBS_Misty` 失敗就進 mock」——安靜地把設定錯誤變成假機器人。
現在要 `MISTY_MOCK=1`，沒設就是真的連線並且會真的失敗。

### 尚未驗證（照 §8 的原則，寫進 README）

驅動層送出的 HTTP / WebSocket 格式**只有契約測試**：證明格式對照官方文件正確，
**不證明機器人會照做**。上面第 1–3 點正好說明為什麼這條線要畫清楚——那三個缺陷
全部是「格式錯了但本地完全看不出來」。

---

## 12. 改成重寫 —— 以及兩個被量測推翻的前提

> 定於 2026-08-11，`/grill-with-docs` 之後。這一節推翻了 §5 的部分內容與 §7 的原順序，
> 兩者已就地更新。**§5 的缺陷 A1 敘述請連同本節一起讀。**

### 12.1 MediaPipe 的跨幀追蹤不是缺陷（撤回）

M4 #02 回報 face mesh 的跨幀追蹤會拖住讀數，並推論 harness 量到的會是
「缺陷 A + 追蹤延遲」的總和。**這個推論來自一個現實不會發生的測試案例**：一幀之內
臉寬從 100px 跳到 200px，等於人從 100cm 瞬間移動到 50cm。

改用真實軌跡實測（640×480，`focal_length=650`）：

| 情境 | 現行設定（追蹤開啟） | `static_image_mode=True`（關閉追蹤） |
|---|---|---|
| 真人平順走近，30fps、每幀 1.7cm | 最大誤差 **0.8%** | 最大誤差 2.3% |
| 機器人走一步，瞬間 −35cm | 最大誤差 **1.4%** | 最大誤差 1.5% |
| 每幀耗時 | **3.81 ms** | 5.36 ms |

**追蹤在真實情境下不但沒有害處，還比較準（它平滑掉雜訊）而且快 40%。**
`static_image_mode` 維持關閉。#02 的 `test_a_reading_depends_on_the_frames_that_came_before_it`
是有效的觀察（依賴確實存在），但不該被讀成缺陷。

教訓：**用病態輸入量出來的數字，不能當成系統在真實負載下的性質。**

### 12.2 缺陷 A1 的前提在這台機器上不成立

§5 寫「consumer 每幀跑 MediaPipe（30–50ms）」，據此推出 queue 單調成長。

**實測 3.81 ms/幀**（640×480，含 `cvtColor`，M1 Pro + Metal）。差了將近十倍。而 producer
每幀 `sleep(0.01)` 之外還要等 `cap.read()` 回來（真實 RTSP 約 33ms/幀）。
**consumer 比 producer 快將近十倍 → 在這台機器上 queue 不會積。**

這不代表原分析沒有價值，而是**宣稱的範圍錯了**。正確的說法是：

> 這條管線**沒有任何背壓機制**。consumer 只要比 producer 慢就會無限積壓，而且沒有任何
> 東西會阻止它或讓你知道。它現在沒出事，純粹因為這台機器夠快。

這句話在任何機器上都成立，而且可以量：量出 consumer/producer 的成本比，指出翻轉點在哪。
M8 的 Docker 是 x86、無 GPU 加速，很可能就落在翻轉點的另一邊——**「正確性取決於主機夠不夠快」
本身就是缺陷**，而且比原本那句更值得寫進 README。

缺陷 **A2**（時間戳蓋在處理當下）與 **A3**（移動後不作廢樣本）不受影響：那兩個是時間語意
的邏輯錯誤，與機器快慢無關。

### 12.3 決定：重寫，不修補

原 §7 的 M5「修缺陷 A」與 M6「修控制層」合併為一個里程碑：**重寫感知到控制的管線**。

範圍**只到感知→控制那條線**（影格 → 距離 → 走幾公分）。ReAct、記憶、事件流不在內——
那些不是「寫壞了」而是「還沒寫」，混在一起會分不清哪些是修復、哪些是新功能。

`full_robot_v3.py` 轉為**唯讀參考**：不再執行、不再維護，只在需要對照舊行為時去讀。
它仍是 LLM prompt 與記憶折疊邏輯的唯一記載，等 M7 把該搬的搬完再刪。

### 12.4 harness 的任務因此改變

原本：證明舊 code 壞了（**必須是紅的**）。
現在：**證明新管線的延遲有上界、佇列有煞車**。

它從「缺陷的證據」變成「設計的規格」——先量出這台機器上的真實數字，再照著那些數字
設計管線。對履歷作品而言這是更強的敘事：不是「我重寫了一份」，而是
「我先做了量測台，然後照它的數字設計」。

連帶：**M4 #03 作廢**。那張單要求「原封搬移缺陷，一個都不准修」，目的是留證據給碼錶量。
既然不再需要證明舊 code 壞掉，它就沒有存在理由。04 / 05 / 07 幾乎不受影響；
06 從「訂一個現在達不到的門檻」改為「訂新管線必須達到的上界」。

### 12.5 fixture 的可用範圍（04 / 05 需要）

合成到 640×480、`focal_length=650`、`real_face_width_cm=15` 時：

**2026-08-11 更新(M4 #04,#05 再更正)**:下表用全新偵測器逐距離量,誤差以**回報距離
相對真值**表示,正號代表把人看得比實際遠。

> ⚠️ **這張表量的是冷啟動,不是 harness 的跑法。** harness 餵給一個偵測器的是連續
> 序列,而跨幀追蹤會讓後續影格準得多。同樣的合成器、改用連續序列量:
> 155cm −1.3%、145cm 0.0%、130cm 0.0%、120cm 0.0%——**遠端沒有隨距離變化的偏差**。
> #05 原本據此表推論「遠端偏差會扭曲互相關」,該推論已撤回。
> 這張表仍然有用,因為**每次重放的第一幀必然是冷的**。

| 真值 | 臉寬 | 回報距離 | 誤差 |
|---|---|---|---|
| 60 / 72 / 85 / 100cm | 162 / 135 / 115 / 98px | 相同 | **0.0%** |
| 115cm | 85px | 116cm | +0.9% |
| 130cm | 75px | 132cm | +1.5% |
| 160cm | 61px | 170cm | **+6.2%** |
| ≥195cm | ≤50px | — | 偵測不到 |

> 原本這裡寫「60px 少算約 8%」,語意不清:少算的是**臉寬**(MediaPipe 把臉量得比畫上去的窄),
> 而**距離因此被高估**。兩種讀法差一個正負號,對 05 訂軌跡起點是實質差別,故改為只寫回報距離。

控制器在 `d > target + tolerance = 72cm` 就開始命令前進，**所以 72–130cm 這整段
（控制律真正作用的範圍）fixture 都是準的**。只有軌跡起點拉到 130cm 以外才會踩到誤差區。

> #02 的 comment 寫「接近控制器大約從 160cm 開始作用」，與 config 對不上——160cm 是
> fixture 的 8% 誤差線（60px），不是控制器的作用起點。已更正。

軌跡起點的選擇因此是 05 要明寫的決定：起點 ≤130cm，或接受遠端誤差並標註。

---

## 13. M5 — 可信 approach 後端的結果

> 完成於 2026-08-13。範圍停在 ReAct 將來會呼叫的 deterministic backend；沒有展開
> Audio、事件流、LLM tool registry 或 ReAct orchestration。

### 13.1 交付的窄介面

- `misty_agent.perception.distance.DistancePipeline` 只保留 process 內最新影格，距離讀數攜帶
  process ingress 與 detection completion 時間；process 之外的 transport lag 仍不可見。
- `misty_agent.control.approach.approach()` 隱藏輪詢、兩筆新樣本中位數、移動失效 epoch、
  settle、步數與整次 deadline、驅動錯誤轉譯。公開結果仍是 `arrived`、`lost_user`、
  `timeout`、`drive_error` 與已執行步數。
- `plan_step()` 是唯一正式控制律。Runtime 直接呼叫；reachability 直接掃描；robustness
  透過 public `approach()` 間接呼叫；測試不另抄公式。

### 13.2 證據與邊界

`docs/measurements/m5-approach-report.md` 由 `.venv/bin/python -m harness` 產生，刻意把四種
證據分開：process-local measurement、parameter sweep、conditional simulation、UNVERIFIED。

| 證據 | 2026-08-13 結果 | 能主張的範圍 |
|---|---|---|
| Production `DistancePipeline`，三次 real-time synthetic replay | process-local lag p95 **43ms**；同次最嚴格 2× floor bound **74ms，PASS** | 真實 MediaPipe、thread 與 clock；沒有 Misty、網路或 sensor transport |
| Transport-lag sweep，0.05s 網格 | 在 configured 2× motion multiplier 下收斂至 **0.65s**；**0.70s** 第一個失敗即 safety-floor breach | 參數掃描，不是量到真實 sensor lag |
| M4 的 100→44cm 反例 | public `approach()` 在 2×、零 transport lag 下抵達且不低於 45cm | 只在最大單調位移 ≤ `max_actual_motion_multiplier` 時成立 |
| 高延遲時的 raw `arrived` | 0.70s 之後仍可因不可見的 transport staleness 回報 `arrived`；report 以 simulator truth 改列失敗 | 說明 public status 不是硬體真值，安全異常不在證據中被成功狀態掩蓋 |

M4 的 1.55/1.60/1.75s 舊數字保留作 pre-rewrite 歷史，**不可直接拿來說 M5 退步**：
M4 掃的是 1× 完美驅動且手動迴圈；M5 發布的是 configured worst case 2×，並完整經過
public `approach()` 的 freshness、median 與 settle 語意。

條件式安全還假設：距離尺度在模擬模型內正確、動作沿命令方向單調、一次命令的最大瞬間
位移（不是只看最後淨位移）不超過 2×。超過倍率、慣性瞬間超衝、真實 focal error、馬達
deadband、RTSP lag 與真機 API 行為全部仍是 UNVERIFIED。`approach_user()` 與 public
`approach()` 都從未在硬體執行。

### 13.3 與早期計畫的偏離

1. **沒有新增第五種 public safety status。** Runtime 看不到 delayed reading 背後的物理真值；
   假裝能回報 `collision` 會製造證據。四個既定 status 保持不變，harness 另存 raw status 與
   truth-audited outcome。
2. **沒有建立 `ApproachPolicy` 子模型。** Frozen `Settings` 仍是 config 入口，控制模組只依賴
   `StepPolicyConfig` protocol 的窄切片。為一張 ticket 改環境變數與所有呼叫端的巢狀形狀，
   風險大於 locality 收益。
3. **M5 產物另寫新檔。** `python -m harness` 現在寫
   `docs/measurements/m5-approach-report.md`，不覆蓋 M4 的歷史 before-state。

---

## 14. M6/M7 重整與 gate/report 原則

> 定案於 2026-08-20 的 grilling。與 §12 同性質（里程碑重整），因此記在這裡而不是新開
> `docs/adr/`：同一類決定分散在兩個地方，比沒有紀錄更糟。

### 14.1 Journal 從 M6 移到 M7

原 M6 綁著兩件不相干的事：事件流，以及 `test_sim.py` 遷 pytest。只有前者依賴 ReAct。

**事件流唯一真實的生產者是 `react.py`。** 曾考慮在 `approach()` 注入 optional emitter，
讓 M6 有一個真實生產者來驗證 schema —— 但 `approach()` 是**控制層**的生產者，而 schema
要服務的是 **ReAct 層**（`llm_call` / `tool_call` / `observation` / `turn`）。用控制層事件
驗 ReAct schema，就是 §12.1 與 §12.5 那條「量測設定必須等於生產設定」的第三次現身。

於是：**M6 = 測試套件收斂**（`.scratch/m6-test-suite-consolidation/spec.md`），
**M7 = ReAct + Journal**。

**M7 的 ticket 順序是硬的**：spec → journal schema + golden files（先 commit）→ tools / react。
Journal 是 M7 測試的斷言標的；如果它與 `react.py` 在同一批工作裡長出來，斷言的詞彙就會被
實作反向塑形。保住這個性質的不是里程碑邊界，是里程碑**內部**的 ticket 順序 —— 而這個 repo
的 commit 粒度本來就是 per-ticket，所以 git 歷史看得到順序。**這句話必須留在 M7 的 spec 裡**，
否則下一個 session 會直覺先寫 `react.py`。

### 14.2 Measurement 設門檻，Sweep 只報告

這條原則一直存在，只是隱含在兩個模組的行為差異裡，沒有被寫下來：

| | 例子 | 處置 |
|---|---|---|
| **Measurement** —— 觀察本 process 跑真實程式碼得到的數字 | 讀數延遲 p95 | 有硬 gate（2× floor bound） |
| **Sweep** —— 對從未量過、沒有硬體就量不到的參數做確定性探索 | `sensor_transport_lag_s`、噪音 δ_px | 只報告 Envelope，零斷言 |

`harness/robustness.py` 已明文寫著「Nothing here is a threshold」。M6 新增的噪音 Envelope
與 transport lag 同級 —— **只報告**。但「封閉式噪音模型與真實偵測器一致」是 Measurement，
**要有斷言**。

「先量再定」在噪音這件事上的落點因此是：**定的是模型對不對，不是噪音容忍度該多少。**

### 14.3 `test_sim.py` 整個刪除，不遷移

`HANDOFF.md` 原本寫「`test_sim.py` 遷 pytest」。實際盤點後這個描述會導致做白工：

- **T1–T3、T5–T7 已有更強的 public-seam 版本**（`test_with_no_lag_and_perfect_calibration_the_robot_arrives`、
  `test_the_two_x_counterexample_stays_outside_the_safety_floor`、`test_a_slow_robot_undershoots_rather_than_overshoots`、
  `test_too_close_commands_one_bounded_backward_step_then_arrives`、`test_step_limit_returns_timeout_and_stops_issuing_commands`）。
  這些是「確認後刪除」，不是遷移。
- **T8 / T9 測的是舊主腳本的 brain 與 memory。** M7 改用 function calling 之後，「消毒
  malformed JSON」這個需求根本不存在。搬進 `tests/` 等於把即將消失的需求正式化。
  **Memory 折疊與持久化的覆蓋因此是一個有意識的缺口，登記為 M7 的重建項目——清單見 §14.6。**
- **T4（量測噪音）完全沒有對應**，而且它的模型是錯的，見 §14.4。

### 14.4 噪音模型：參數是像素，不是公分

`distance_cm = focal_length × real_face_width_cm / pixel_width`。距離與像素寬成反比，所以
固定的像素抖動造成的公分誤差隨 **d²** 放大。預設常數（650 × 15 = 9750 px·cm）下：

| 真實距離 | 臉寬 | 1px 抖動 |
|---|---|---|
| 45cm（safety floor） | 217px | **0.21cm** |
| 60cm（target） | 163px | 0.37cm |
| 100cm | 98px | 1.03cm |
| 200cm | 49px | **4.10cm** |

舊 T4 的均勻 ±8cm 因此在 45cm 處相當於約 38px —— 臉寬的 17%，物理上不可能；在 200cm 處
只有約 2px。**近處過嚴、遠處過鬆，而近處正是安全結論被決定的地方。**

M6 因此以 **δ_px 為掃描參數**（明列 UNCALIBRATED），二維掃 transport lag × δ_px，但
**報告只寫邊界曲線**：二維是實驗的形狀，不是報告的形狀。失敗模式除了 safety floor 越線
與未收斂之外，另加**方向反轉次數** —— 那是噪音的特徵失敗模式，它不越線也可能照樣回報
`arrived`，兩個既有軸對它都是瞎的（M4 #08 的教訓）。

### 14.5 `CONTEXT.md` 建立

同一次 grilling 產出 repo 的第一份 `CONTEXT.md`。它只是詞彙表，不含實作細節，`PLAN.md`
繼續持有決策與證據。收錄的詞裡有三組是**因為互相碰撞才需要定案**的：

- `Journal`（agent 自己的紀錄）vs `Event`（Misty 推來的硬體訊號，維持廠商用字）
- `Turn`（ReAct 一回合）vs `Step`（控制層一次驅動命令）
- `Measurement` vs `Sweep` vs `Envelope`（§14.2 的區分）

`Episode` 定義為「從外部觸發到回到閒置，保證有界終止」，**內部階段不入定義** —— 舊 FSM 的
PERCEIVE/THINK/ACT 會在 ReAct 化之後變成 Turn 迴圈，寫進定義等於預先綁死 M7。e-stop 記成
`episode_aborted`：它是唯一會讓「保證回到 IDLE」被外力打斷的路徑，不記它，Journal 就無法
用來證明那個性質。

### 14.6 M7 的重建清單（M6 刪除舊 runner 所帶走的覆蓋）

M6 刪掉舊 simulation runner 時，有兩項覆蓋沒有留在 M6 的樹裡。**它們不是被放棄，是
被排進 M7**；記在這裡而不是只寫在盤點裡，是因為盤點是一份時點文件，而這是一份待辦。

| 帶走的覆蓋 | 為什麼不在 M6 重建 | M7 要交付什麼 |
|---|---|---|
| **Memory 折疊與持久化**（舊 T9 五條檢查：視窗上限、事實抽取、檔案寫出、重載後仍在、prompt block 含近期輪次） | 測試伸手進舊主腳本的內部，而 M7 正要重寫那些內部。先搬會搬到即將消失的形狀上 | memory 搬出舊主腳本時，同等或更強的覆蓋要一起長出來 |
| **工具參數的合法性檢查**（舊 T8 三條檢查倖存的那半） | 舊 T8 測的是「消毒 model 回傳的 malformed JSON」。M7 改用 function calling，結構由模型端保證，這個需求會消失 | 但「超出範圍或未知的工具參數要被拒絕，而不是送到機器人」這件事仍然成立，且應與 tool registry 一起交付 |

**這兩條在 M7 完成前，專案沒有對應的可執行覆蓋。** 這是刻意接受的空窗，不是疏漏；
`docs/measurements/m6-coverage-audit.md` 的 T8 與 T9 段落有完整推理。

### 14.7 偵測器有記憶：交叉檢查必須用連續輸入

M6 #03 的交叉檢查第一版用孤立靜態影格餵 `FaceDetector`，結果在 180cm 完全找不到臉。
改成單一偵測器跳著餵（60→90→120→…）之後，**改成在 120cm 失敗**。同一段距離、同一張
素材、同一組參數，只因為前一幀不同就換了答案。

原因是 `FaceDetector` 開著跨幀追蹤，與生產管線一致 —— 而 `harness/synthetic_camera.py`
的 `measure_face()` 早就為此把 `static_image_mode` 設成 `True`，並在 docstring 寫明理由
（「tracking with nothing to track from」）。生產環境餵的是 30fps 連續影片，不是 30cm 的跳躍。

改成 2.5cm 步進、55→185cm 的連續行走之後：**整段零漏偵測**，ratio 散布 1.1%，量到的敏感度
落在封閉式預測的 10% 容差內。

⚠️ **不要把「−0.7385 vs −0.7385」讀成四位數的吻合。** 那是量化剛好落在整數上：偵測器在
60/120cm 回報 59/119、在 90/180cm 回報 89/179，差值剛好是 60 與 90，於是相除後與預測逐位
相同。真正被證明的是「落在容差內」，不是「精確到小數第四位」。

**這是 §12.1、§12.5 之後同一條教訓的第三次**：量測設定必須等於生產設定。三次的形狀都一樣
—— 數字是真的，錯的是量的方式。§12.5 尤其接近：當時就是用「每個距離一個全新偵測器」量的，
而 harness 餵的是連續序列，兩者差一個數量級。**這次是同一個陷阱換一個入口又踩了一次。**

`_readings_along_a_walk()` 的 docstring 記著這件事，因為未來最可能的「簡化」就是把行走換回
孤立影格 —— 那會讓交叉檢查在遠端安靜地失去主體。

順帶一提，第一版交叉檢查還有一個獨立的毛病：用 60→72cm 這種小間距去相減兩個各帶 2% 誤差的
讀數，誤差傳遞到 22%，測到的是自己的條件數而不是模型。改用間距 60cm 與 90cm 的配對後降到
約 6%。容差是從已記載的偵測器精度推出來的，不是照觀察到的數字回頭配。
