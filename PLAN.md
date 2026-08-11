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
| 硬體 | **永久無實機**。`approach_user()` 從未在真機執行過 |
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

→ **M6 的工作因此改變**：不是「讓 guard 活起來」，而是
①把 guard 改成明示的不可達斷言（或移除並在註解指向 validator），
②**真正要解的是「clamp 命令距離 ≠ clamp 實際距離」**——validator 完全沒碰這個，校準誤差仍會讓機器人衝過 45cm。這才是缺陷 B 的實質。

### C. `max(8.0, ...)` 是 dead code 兼未爆彈
`full_robot_v3.py:706`：`abs(delta) > 12` ⟹ `abs(delta)×0.7 > 8.4 > 8`，下限永不生效。
但 `DISTANCE_TOLERANCE_CM` 一旦調到 11 以下就會活過來，而**後退方向完全沒有 clamp** → 後退超衝 → 來回震盪至 step cap。
→ **實作 + 補後退方向的 clamp**。

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
- `test_sim.py`（現為自寫的 28 案例 runner，非 pytest）→ **遷移到 pytest**
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
| **M4** | harness | 合成影格 + 真值軌跡 + 延遲量測。**任務已改**，見 §12 |
| **M5** | 重寫感知→控制管線 | 原 M5（缺陷 A）與 M6（缺陷 B/C/E）合併。不是修補，是照 harness 的數字設計一條新管線，把已知的坑一次避開 |
| **M6** | 事件流 | `agent/events.py`；`test_sim.py` 遷 pytest |
| **M7** | ReAct | `tools.py`（12 工具，註冊表）+ `react.py`（step cap / 感知快照 / TTS 抑制窗） |
| **M8** | 部署 | Docker multi-stage + CI workflows |
| **M9** | 文件 | README 與架構圖重寫 |
| **M10** | 收尾 | 開新 repo，乾淨歷史匯入 |

---

## 8. 必須誠實標註的未驗證邊界（寫進 README）

- 驅動層 HTTP / WebSocket 請求格式 —— 只有契約測試，**無實機驗證**
- `CM_PER_SEC_AT_PERCENT`（實際驅動速度）
- `FOCAL_LENGTH`（相機焦距常數）
- `SENSOR_TRANSPORT_LAG_S`（相機→process 的傳輸延遲）
- 馬達 deadband（20% 會不會根本不動）
- RTSP 端到端延遲的真實數量級
- ASR 在 Misty 麥克風 + 環境噪音下的辨識率
- `drive_time` 執行中再下指令的實際行為
- **`approach_user()` 從未在真機執行過**（公開 demo 的 planner 輸出是 `movement: "stay"`）

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
| 1 | Spec (c) | **`forward_clamp_is_reachable` 對合法 config 回答錯誤。** 閉式解只模型化 gain 項，漏了 `min_step_cm` 會把命令步長抬高。反例 `min_step_cm=30`：d=73 時命令 30cm 對上 headroom 28cm，clamp 確實生效，但屬性回 `False`。 | 三個 reachability 函式改為**掃描真實的 `plan_step`**，不再用手推閉式解——這消滅了整類代數推導錯誤。回歸測試 `test_forward_clamp_reachability_accounts_for_the_min_step_floor`。 |
| 2 | Standards #4 | **控制律在測試裡被手抄一份**，真實控制律改變時副本會默默分歧而測試照樣綠。 | 抽出 `misty_agent/control/step_policy.py`，`plan_step()` 成為唯一實作，三個消費者（`approach_user`、reachability 分析、測試）共用。 |
| 3 | Spec (b) | reachability 分析寫在 `config.py` 裡是 scope creep，且分層不對。 | 移到 `control/step_policy.py`。`config.py` 現在只有資料與不變量。 |
| 4 | Spec (a) | `llm_temperature` 宣告了卻沒接線；`TRIGGER_COOLDOWN=3.0` 與記憶呼叫的 `temperature=0.2/0.0` 仍是字面值。**宣告了卻沒接線比字面值更糟——它看起來可調，實際不可調。** | 全部接線，並新增 `memory_summary_temperature` / `memory_fact_temperature` / `trigger_cooldown_s`。 |
| 5 | Standards #1 | `.env.example` 把 `MISTY_MAX_REACT_STEPS` 當成能用的東西宣傳。 | 獨立成「DECLARED BUT NOT YET WIRED」區塊並註解掉，標明各自落在哪個里程碑。 |
| 6 | Spec (a) | `CUBS_Misty.py` 的三行清理掛在 §3（M1），但沒做。 | §3 改為**明確延後到 M3** 並寫出理由。 |
| 7 | Spec | §5-B 的「原本的推論是錯的」把一個設計選擇說成發現。 | 改寫成「被 M2 的一個設計選擇擋掉了（不是原分析算錯）」。 |

### 已知未修（刻意）

- **Middle Man / Shotgun Surgery**：`full_robot_v3.py` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派，留下同一份資料的兩條存取路徑。**刻意保留**——`full_robot_v3.py` 會在 M3–M8 被拆進 `misty_agent/`，屆時整個區塊消失。現在改只是把同一份工作做兩次。
- **Data Clumps**：六個控制律欄位總是一起旅行，`ApproachPolicy` 子模型想被生出來。M6 重寫控制層時一併處理。
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

| 臉寬 | 對應距離 | MediaPipe 還原精度 |
|---|---|---|
| ≥ 75px | ≤ 130cm | 誤差 < 1.2% |
| 60px | 162cm | 少算約 8% |
| ≤ 50px | ≥ 195cm | 偵測不到 |

控制器在 `d > target + tolerance = 72cm` 就開始命令前進，**所以 72–130cm 這整段
（控制律真正作用的範圍）fixture 都是準的**。只有軌跡起點拉到 130cm 以外才會踩到誤差區。

> #02 的 comment 寫「接近控制器大約從 160cm 開始作用」，與 config 對不上——160cm 是
> fixture 的 8% 誤差線（60px），不是控制器的作用起點。已更正。

軌跡起點的選擇因此是 05 要明寫的決定：起點 ≤130cm，或接受遠端誤差並標註。
