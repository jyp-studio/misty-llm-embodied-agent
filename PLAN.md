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
│   ├── journal.py            # Journal：事件型別 + 訂閱（M7 grill 後改名，見 §15）
│   ├── react.py              # ReAct 迴圈
│   ├── tools.py              # Tool 參數型別 + dispatch（註冊表模式）
│   └── memory.py             # 三層記憶（**重新設計**，非搬移，見 §15）
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
- 工具集 ~~**12 個左右**~~ → **定為 9 個**（M7 grill；`back_up` 砍掉，見 §15.2），註冊表模式，加工具 = 一個函式 + 一份參數型別，不動 `react.py`
- `MAX_REACT_STEPS = 5` —— **初值，用事件流量測後修正**
- **無獨立快路徑**：LLM 第一輪就能輸出 `done`（自主終止本來就是 ReAct 判準之一，硬編碼特例等於自廢武功）
- **必須保留 step cap**：目前系統最強的性質是「每個 episode 可證明回到 IDLE」，ReAct 化最容易弄丟這個

### 分層開放（工具集邊界）
```
直接開放（加參數 clamp）：display_image(表情) / move_arms / move_head /
                          change_led / play_audio / speak / look_around
高階意圖（走確定性閉環）：approach                  ← LLM 不碰 velocity / timeMs
終止：                    done

（~~`back_up`~~ 已砍除：`approach()` 本來就會後退。見 §15.2）
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

**連帶必須處理**：目前 ACT 期間整段 `perception.pause()`，新語音進不來。要把抑制範圍縮小到**只在 TTS 播放期間**。

> ⚠️ ~~用 `speak` 回傳的 `spoken_ms` 當抑制窗~~ —— **這個做法不存在。** Misty 的 TTS
> 不回傳任何時間資訊；舊主腳本是用字數估計（`words / 2.2 + 0.5`，上限 12 秒）並已自行
> 標註未校準。M7 保留估計但把速率搬進 `config.py` 明列 UNCALIBRATED。見 §15.4。可在 harness 測：餵「機器人講話期間使用者插話」情境，斷言插話有收到、自己的話沒有。

### 結構化事件流（`agent/journal.py` —— M7 grill 後定名為 **Journal**，見 §15.3）
每件值得記錄的事發出有型別的紀錄，終端機輸出退化成其中一個渲染器：
```jsonl
{"t":12.34,"type":"llm_call","turn":1,"latency_ms":1840,"tokens":{"in":1203,"out":47}}
{"t":14.18,"type":"tool_call","turn":1,"tool":"approach","args":{}}
{"t":19.02,"type":"observation","turn":1,"result":"arrived","distance_cm":63}
{"t":19.90,"type":"episode_done","turns":2,"steps":3,"total_latency_ms":5600}
```

> ⚠️ **原範例用 `step` 指 ReAct 的一輪，那與 `CONTEXT.md` 衝突。** `Step` 是控制層的一次
> 驅動命令，ReAct 的一輪是 `Turn`。原本的 `"steps":2` 更分不出是哪一個 —— 上面已改成
> 兩個欄位，因為一次 Episode 兩者都有意義。`t` 的語意見 §15.3。
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
| **M8** | 可執行性與 demo | `main()` + 系統提示 + Journal 落地 + 本機 demo 介面。**不再是「部署」**，理由見 §16 |
| **M9** | 文件 | README 與架構圖重寫 |
| **M10** | 收尾 | 開新 repo，乾淨歷史匯入 |

**表上沒有研究方向，那是刻意的。** 使用者想做的「社交機器人如何判斷何時、是否、以及如何主動
發起互動」不在這張表上 —— 因為這張表是**工程**的順序，而那是一個研究問題，它需要的是文獻、
假設與實驗設計，不是一個里程碑編號。等它有了形狀再決定要不要進表（2026-09-06 決定）。

---

## 8. 無法驗證的邊界（本專案沒有硬體）

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

**這一節的語氣在 2026-09-06 改過，因為它原本說錯了一件事。**

原標題是「必須誠實標註的**未**驗證邊界」，語氣是「還沒量」—— 暗示總有一天會量。事實不是這樣：
**這個專案沒有 Misty II，而且不會有。** 上面每一條都不是「還沒驗證」，是「本專案永遠不會驗證」。

那兩句話對讀者的意思完全不同，而後者是更強也更誠實的主張。「還沒量」讀起來像一個半成品；
「沒有硬體，所以以下每一條都只是文件說的、不是機器做的」則把範圍講清楚了 —— 這是一個在模擬上
做到極致的系統，它主張的每一件事都停在它能證明的地方。

處理原則不變：①隔離成明確標註的校正參數，②用參數掃描證明控制律對其誤差的魯棒範圍，
③在 README 誠實區分**已模擬驗證** vs **從未在硬體上執行**。

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
  > **已解除（M7 #12）**：`full_robot_v3.py` 已刪除，這個區塊隨它消失。
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
| ~~**Memory 折疊與持久化**（舊 T9 五條檢查：視窗上限、事實抽取、檔案寫出、重載後仍在、prompt block 含近期輪次）~~ **已還（M7 #09）** | 測試伸手進舊主腳本的內部，而 M7 正要重寫那些內部。先搬會搬到即將消失的形狀上 | `misty_agent/agent/memory.py` + `tests/test_memory.py`。五條檢查全部有對應，而且**更強**：視窗上限與 prompt block 現在是純函式，不需要假的 OpenAI client 就能測；折疊改成不刪除，所以「重載後仍在」連 Exchange 原文一起涵蓋。見 §15.26 |
| ~~**工具參數的合法性檢查**（舊 T8 三條檢查倖存的那半）~~ **已還（M7 #04）** | 舊 T8 測的是「消毒 model 回傳的 malformed JSON」。M7 改用 function calling，結構由模型端保證，這個需求會消失 | 但「超出範圍或未知的工具參數要被拒絕，而不是送到機器人」這件事仍然成立，且應與 tool registry 一起交付 |

**這兩條在 M7 完成前，專案沒有對應的可執行覆蓋。** 這是刻意接受的空窗，不是疏漏；
`docs/measurements/m6-coverage-audit.md` 的 T8 與 T9 段落有完整推理。

**兩筆都已還清**：工具參數在 #04（`tools.py` 的型別即 schema 即驗證），memory 在 #09
（`memory.py`）。§14.6 這張表到此結案。

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

### 14.8 反轉不是 lag 造成的，而且對倍率非單調

M6 #04 的 ticket 原文預測「高 transport lag 就能逼出方向反轉」。**實測推翻了它**：在
configured 的 `max_actual_motion_multiplier=2.0` 下，掃到 3 秒 lag 都是零反轉。抵達帶有
24cm 寬，而步長上界本來就替 2× 行走預留了 headroom，單靠讀數過期帶不動它越過人。

**但「反轉只在離開校準假設時出現」同樣是錯的**，而且錯得比前一句更值得記住：

| 行走倍率 | lag 2.0s 的反轉數 | public status | truth-audited | 最近距離 |
|---|---|---|---|---|
| 1.5×（**假設範圍內**） | **2** | timeout | `safety_floor_breach` | 7.2cm |
| 2.0×（configured） | **0** | arrived | `safety_floor_breach` | −9.9cm |
| 2.5× | 2 | arrived | `safety_floor_breach` | −44.9cm |
| 3.0×（lag 0） | 7 | timeout | `safety_floor_breach` | 25.1cm |

掃過 61 個 lag（0→3.0s，0.05 步進）：**1.5× 有 12 個 lag 反轉**，集中在 1.85–2.40s 這一段
連續帶；**2.0× 一個都沒有**。

三件事因此成立：

1. **反轉對行走倍率非單調。** 比假設的最壞情況「更溫和」的倍率不是更溫和的案例。陰性對照
   只能綁在 configured 倍率上，不能寫成「假設範圍內都不反轉」。
2. **不能假設 row 之間可以內插。** 1.85–2.40s 那條帶只有 0.55 秒寬；M6 #05 的網格是 0.05s，
   再粗一點就會整段跨過去 —— M4 #08 已經為這條教訓付過一次錢。
3. **乾淨的反轉數不是安全結論。** configured 倍率配 2 秒 lag 零反轉、回報 `arrived`，實際
   卻開到人身後 9.9cm。**而且整張表 truth-audit 之後全是 `safety_floor_breach`** —— raw
   status 那一欄的 `arrived` 與 `timeout` 兩者都掩蓋了同一件事，這正是 §13.3 第 1 點要
   另存 truth-audited outcome 的理由。

三條軸（越線、收斂、反轉）彼此獨立，這正是要分開數的理由。

### 14.9 粗網格第二次咬人：抵達帶遠端的量化假象

M6 #07 把盤點裡的「推論」換成直接斷言時，順手把 2× 的起始距離掃描從 10cm 改成 **1cm**
—— 因為驗收條件要求涵蓋舊 runner 用過的 150／160／200／300cm。細掃之後跑出 10cm 網格
看不到的東西：

**部分起始距離下，public `approach()` 回報 `arrived`，但 truth audit 判 `overshoot`。**
它們**每 70cm 出現一次**（＝ 2 × `max_step_cm`），而且**沒有盡頭** —— 掃到 600cm 仍在：
142、212、282、352、422、492、562cm。這是有界步長落在同一個相位，不是雜訊。

**這不是安全問題**，而且方向恰好相反：

| start | final | 超出抵達帶遠端 | closest | 安全底線 |
|---|---|---|---|---|
| 142cm | 72.04cm | 0.04cm | 72.04cm | 未觸及 |
| 212cm | 72.08cm | 0.08cm | 72.08cm | 未觸及 |
| 282cm | 72.12cm | 0.12cm | 72.12cm | 未觸及 |
| …每 70cm 一次 | | 每多一步 +0.04cm | | |
| 562cm | 72.28cm | 0.28cm | 72.28cm | 未觸及 |

抵達帶是 `[48.0, 72.0]`。機器人停在 72.04cm —— **比帶子更遠**，不是更近。成因是讀數被截成
整數公分：真值 72.04 時控制器讀到 72，落在帶內，於是宣告抵達。

**超出量的上界是 `max_approach_steps` × 0.04cm ≈ 0.32cm，不是「一公分」。** 初版把它寫成
「被一公分的量化所界定」，那聽起來像個上界但不是：誤差每步累積約 0.04cm，若步數上限調高，
總和沒有東西擋著它越過一公分。

三點後果：

1. **M4 #08 的教訓再次應驗。** 當時是 0.5 秒的粗網格跳過超衝帶，把後面的碰撞誤報成第一個
   失敗；這次是 10cm 的粗網格整段跨過所有不收斂的起點。**粗網格會指錯結論，不只是不精確。**
2. **但 1cm 也還是粗的。** 以 0.01cm 取樣，那些「點」其實是寬約 1cm 的**帶**
   （141.97–142.95 等）。這條記錄本身就示範了自己在講的事：解析度決定你看到的形狀。
3. **M6 #05 的報告不得把這幾列當成安全失敗。** 它們是量化假象，方向遠離人。但也不能藏起來
   —— public `arrived` 與模擬真值在**零 transport lag** 下就已經分家，沒有過期讀數可以怪。

由 `test_the_arrival_band_edge_is_missed_by_a_hair_at_a_regular_spacing` 釘住：它自己找出
不收斂的起點、斷言間距等於 2 × `max_step_cm`、並以步數上限乘以每步 0.04cm 作為超出量的界。

**順帶更正一項對 safety floor 的誤解。** 掃描測試釘住的是**抵達帶**的 headroom，不是
safety floor 的：拿掉 `floor_cap` 的除數，整套測試無人察覺。那是**預期結果**而非漏洞 ——
§5 已記載該 clamp 對任何合法 config 都不可達，`test_defect_B_safety_floor_branch_is_
unreachable_for_EVERY_valid_config` 正是證明它的。M6 #07 的 ticket 註記初版把這件事說反了。

### 14.10 M6 的結果：抖動幾乎不動 envelope

`docs/measurements/m6-noise-envelope-report.md` 由 `python -m harness` 與 M5 報告**同一次執行**
產出。二維掃描：transport lag（0→3.0s，0.05 步進，61 點）× 像素抖動（0／1／2／4／8／16px）
× 5 個 seed ＝ 1830 個網格點。

**主結果：16px 的偵測抖動只把 transport-lag envelope 從 0.65s 推到 0.60s —— 一個網格步。**

| δ_px | envelope（最差 seed） | 最佳 seed | seed 分歧 |
|---|---|---|---|
| 0 | 0.65s | 0.65s | 否 |
| 1 | 0.65s | 0.65s | 否 |
| 2、4、8 | 0.65s | 0.70s | 是 |
| 16 | **0.60s** | 0.70s | 是 |

取**最差 seed**作為表頭數字：控制器的韌性只等於它最倒楣的那一次抽樣。最佳 seed 並列著，
是為了讓分散度看得見而不是被平均掉。

**三件值得記下的事：**

1. **抖動不是這條管線的主要風險。** M4 #06 量到的 process-local 延遲是 43ms，而
   envelope 在 0.6s 以上 —— 抖動要到 16px（在 200cm 處相當於 66cm 的距離誤差）才動得了
   一格。真正吃掉裕度的是 transport lag，而那個從未被量過。
2. **反轉全部落在已經失敗的列。** 1830 列裡 62 列有反轉，**沒有任何一列同時是收斂的**。
   所以在這個掃描範圍內，反轉是「已經壞掉」的症狀而不是獨立的失敗模式。報告明寫若哪天
   有收斂的列反轉了，那就是新發現。
3. **失敗列數要看分母。** 1401/1830 列越過安全底線 —— 那不是發現，是「lag 軸刻意掃到
   遠超過邊界的 3 秒」的必然結果。報告把分母與這句話放在表格前面，因為沒有分母的
   「1401 列越線」會被讀成災難。

**§14.9 的量化假象不在這張表裡**：它只在特定起始距離（每 70cm 一次）出現，而掃描從單一
起點跑。報告有明說這件事，而不是讓它靜靜地不存在。

### 14.11 M5 報告有一處 1ms 的自相矛盾，程式已修、產物待重產

M6 #05 的 review 發現：`m5-approach-report.md` 的表頭寫 `Reading lag, p95 | **43–44 ms**`
（跨三次執行的範圍），而下方的 claim 欄寫 `p95 43ms`（只取第一次）。兩句都為真，但同一份
文件用兩種聚合方式講同一個量，讀者會以為其中一個錯了。

`harness/report.py` 的 `_claims()` 已改成與表頭用同一個範圍。**但產物還沒重產**，因為
重產當下這台機器的 load average 在 2.3–4.5 之間（M6 期間的壓力測試與 review agent 留下的），
而在那個狀態下量到的 p95 是 **48–65ms**，不是靜態時的 43–44ms。上界仍 PASS（65 vs 77ms），
但那份數字量到的是機器不是管線 —— §12.2 記的正是這件事。

所以 M5 的產物維持 2026-08-24T11:02 那次（安靜時）的內容，那 1ms 的矛盾會在**下一次於安靜
機器上執行 `python -m harness`** 時自動消失。

**順帶記一個可重現性的差異：M6 的報告與 M5 的不同，它是逐字元決定性的。** 掃描跑的是假時鐘
與 seeded 噪音的純模擬，沒有即時量測，所以機器負載影響不了它 —— 連跑兩次雜湊相同。這也是
為什麼本次可以只提交 M6 的產物而不必連帶提交一份被污染的 M5。

---

## 15. M7 的定案（grill，2026-08-24）

> spec 在 `.scratch/m7-react-and-journal/spec.md`。本節只記**決定與理由**，特別是那些
> 推翻了 §2／§4 原文的部分 —— 那五處已在原地更正並加註。

### 15.1 M7 只做單次 Episode，不做外層迴圈

公開入口是「餵一個觸發輸入，跑完一次 Episode」。**不做**「一直等使用者說話」的外層迴圈。

理由：外層依賴語音串流，而 `AudioStream` 的轉錄與 VAD 擠在同一條 thread 上是 HANDOFF §4
記著的**尚未處理的已知缺陷**。把它拉進 M7 等於在沒修的地基上疊 ReAct。而單次 Episode 是個
乾淨的 seam：測試餵一個觸發輸入、斷言 Journal，不需要 audio 也不需要真的等待。

### 15.2 工具集定為 9 個，`back_up` 砍除

`speak`、`display_image`、`move_arms`、`move_head`、`change_led`、`play_audio`、
`look_around`、`approach`、`done`。

**`back_up` 站不住腳**：`approach()` 本來就會後退 —— 主體太近時它自己會退，
`test_too_close_commands_one_bounded_backward_step_then_arrives` 就在測這件事。所以
`back_up` 要嘛與 `approach` 重複，要嘛意思是「退到比預設 target 更遠處」，而 `approach()`
**沒有距離參數**。兩個 Tool 做同一件事，模型會挑錯，而且**從 Journal 上看不出它為什麼挑錯**。

將來若真需要「請退遠一點」，那是給 `approach` 加一個受 clamp 的目標距離參數，不是加第二個
Tool。「12 個左右」是 M0 的估計；現在有實際的控制層了，估計讓位給事實。

**Tool 參數用型別定義，schema 由型別產生。** 一份定義同時負責宣告與驗證，兩者不會漂 ——
這個 repo 已為「兩份會各自漂移」做過至少三次決定（§10、M6 #01 的盤點、本節）。這同時還掉
§14.6 欠的工具參數檢查那筆帳。

### 15.3 Journal：型別是契約，JSONL 是格式

- **每種事件一個 frozen 型別。** 共同欄位只有三個：時間、種類、Episode 識別。**`turn` 不是
  共同欄位** —— Episode 開始那筆沒有 Turn，硬塞會逼出一個 Optional，然後每個讀者都要處理它。
- **時間是 Episode 相對秒，來自單調時鐘，時鐘可注入。** 沿用 `approach()` 既有的 Clock
  protocol 與假時鐘，golden files 因此天然可逐字元比對。Episode 開始那筆額外帶**一個**絕對
  wall-clock 戳記給人對時。
- **契約是型別，JSONL 是序列化格式。** 版本欄位只放在 Episode 開始那一筆。**M10 之前 schema
  不保證穩定** —— 這是履歷作品不是發布的 API，假裝穩定要付相容性的代價。
- **寫入加鎖，任何 thread 直接寫。** 不採「丟佇列由主迴圈收」：那會讓緊急停止**發生的時間**
  與**被記下的時間**差開，而那個差距正是要量的東西。

### 15.4 Observation 與 Snapshot

**Observation = Tool 自己的結果 + Snapshot**，Snapshot 由迴圈附加而非每個 Tool 各自組裝
（對每個 Tool 都一樣，放進 Tool 就是複製九份）。

**Snapshot 刻意固定為三樣**：主體距離、是否看得見、是否聽到新的話。三樣本來就在跑，零額外
模型呼叫、零額外等待。更豐富的感知是**一個模型自己去呼叫的 Tool**，不是加寬 Snapshot ——
那會讓每一步都付那個成本，而 §4 已明確否決每步重跑影像模型。

失敗原因靠 `approach()` 既有的四個狀態承載，不加寬 Snapshot。Observation 送給模型時序列化
為 JSON，**不並陳一份人話摘要** —— 同一個事實兩份拷貝會漂。

**TTS 抑制窗：§4 原文的做法不存在。** Misty 的 TTS 不回傳時間；保留字數估計，但把速率常數
搬進 `config.py` 並明列 UNCALIBRATED（它現在硬編在舊主腳本裡）。抑制窗只涵蓋播放期間，
靠注入時鐘讓它可測。

### 15.5 Memory 重新設計，不是搬移

§2 原本寫「三層記憶（現有邏輯搬移）」。**改為重新設計。**

一份只增不改的 **Exchange** 紀錄是唯一真相，摘要與事實是它的衍生物。取最近幾輪變成**純函式
的切片**（不需模型，微秒級可測，§14.6 欠的五條檢查大半落在這裡）。摘要與事實抽取**在 Episode
邊界各做一次**，不是每個 Turn 一次 —— ReAct 之下一個 Episode 有多個 Turn，但使用者只說了
一次話，每輪抽取是在對著沒有新東西的紀錄抽。

**模型的訊息串不是 memory。** 那是一個 Episode 的工作脈絡，隨 Episode 丟棄；Exchange 是跨
Episode 活著的東西。兩者不得合而為一。

**不引入向量檢索。** 一個 Episode 五到十秒、一次 session 幾十輪，語料規模撐不起嵌入呼叫與
額外相依的成本。

曾考慮讓 memory 直接折 Journal（不自己記帳），**否決**：§4 給 Journal 的責任已有三個
（斷言標的、延遲量測、未來 UI），加上「memory 的來源」會讓它為四個理由改變。等 schema 在
M7 穩下來，M8 之後再考慮合併不遲。

### 15.6 Ticket 順序是 spec 的一部分

```
spec → Journal 型別 + golden files（先 commit） → tools / react → 最後刪舊主腳本
```

Journal 是 M7 測試的斷言標的。與 ReAct 迴圈同批長出來，斷言的詞彙就會被實作反向塑形。
**Schema 從 spec 推導，不從實作推導。** Golden files 涵蓋 Episode 的**四種結束方式**：
一個 Turn 就結束、多個 Turn 正常完成、撞到步數上限、被緊急停止中止 —— 少一種就有一條路徑
沒有對照。

舊主腳本在**最後一張票、單獨一支 commit** 刪除：一千多行的刪除 diff 混在其他改動裡，
review 會看不出刪掉的是不是正確的東西。

### 15.7 拒絕理由的措辭：golden 贏，實作讓步（M7 #04 review）

`tests/goldens/episode_ends_after_several_turns.jsonl` 裡那筆被拒的 `move_head` 寫的是：

```
"reason": "pitch 140 is outside the permitted range"
```

而 #04 第一版的 `_explain()` 產出的是 `"pitch: Input should be less than or equal to 26"`。
兩者欄位對得上、**內容對不上**：golden 講**模型送了什麼**，實作講**上限是多少**，而且互相不是
對方的子集。ticket 07 必須重現這個檔案，所以這不是措辭偏好，是 07 會不會卡住的問題。

`tests/goldens/README.md` 訂的規則是「**實作產不出 golden 時，哪一邊讓步是一個決定，要寫進
PLAN**」。這裡**實作讓步**，理由有兩層：

1. golden 是在這個模組存在之前寫的，這正是它的用途。反過來改 golden 去遷就實作，等於讓
   斷言由實作反向塑形 —— §15.6 整節就是為了防這件事。
2. 就算沒有 golden，「你送的 140 超出範圍」對模型也比「上限是 26」有用：要改的是模型送出的
   那個值。

**同時抓到一條把實作釘死在 golden 對面的測試。** `test_the_reason_names_the_argument_and_
what_was_wrong_with_it` 斷言 `"26" in reason` —— 斷言的是上限。它會讓正確的修法變紅。已改成
斷言送出的值，並另外加一條直接**從 golden 檔案讀出** reason 來比對的測試：把字串抄進測試裡的
版本，在有人改了 golden 之後還是會繼續綠。

### 15.8 §4 的分層規則獨立成 `layering.py`，並且**分方向**（M7 #04 review）

原本 `journal.py` 持有一份禁用鍵清單，`tools.py` import 它、**再自己實作一次比對**。這是
§10 講的同一件事有兩份，而且兩份的行為本來就不同 —— 註冊時檢查的是 `model_fields`，序列化時
檢查的是 mapping 的 key。規則移到 `misty_agent/agent/layering.py`，兩邊都是它的使用者。
§15.5 拒絕把 memory 併進 Journal 的理由（不要給 Journal 多一個變動的理由）同樣適用：分層是
§4 的事實，不是 Journal 的事實。

**規則要分方向，這是 review 過程中被 golden 逼出來的。** 第一版寫成「名字結尾是時間單位就
拒絕」，結果四個 golden 全部掛掉 —— 因為 Observation 的 result 裡有 `estimated_speech_ms`
（§15.4 的抑制窗就是靠這個數字），`model_called` 上有 `latency_ms`。這些是**系統回報的量測**，
不是模型下達的命令。定案：

| | 模型選的（Tool 參數、`tool_called.args`） | 系統回報的（`observation.result`） |
|---|---|---|
| 速率（`velocity`、`speed`、`cm_per_sec`…） | 拒絕 | 拒絕 |
| 驅動指令本身的參數名（`timeMs`、`drive_ms`…） | 拒絕 | 拒絕 |
| 其他時間單位（`estimated_speech_ms`、`latency_ms`） | 拒絕 | **允許** |

距離**故意不擋**：§15.2 已經寫明「將來若真需要退遠一點，那是給 `approach` 加一個受 clamp 的
目標距離參數」。在這裡擋掉 `target_distance_cm`，等於替 §15.2 明白留著的決定先做了決定。

**註冊時檢查的對象改成產生出來的 schema，不是 `model_fields`。** 因為 schema 才是模型真正
看到的東西，而兩者不是同一份文件：`Field(alias="linearVelocity")` 在 `model_fields` 裡叫
`v`、在 schema 裡叫 `linearVelocity`；巢狀模型的欄位根本不在 `model_fields` 裡，只在
`$defs`。原本兩條路都是開的 —— 而模組 docstring 宣稱的正是「不可能」。走 alias 那條更糟：
註冊會過，然後 `dispatch` 把每一次呼叫都當成未知參數拒絕，變成一個模型看得到、但永遠叫不動
的 Tool。

### 15.9 `ends_episode` 是註冊時宣告的屬性，不是名字（M7 #04 review）

§4 說沒有獨立快路徑，`test_done_says_the_episode_should_end` 的 docstring 也這樣寫 ——
但它**測不出來**：`build_registry()` 裡唯一 `ends_episode=True` 的 Tool，同時也是唯一叫
`done` 的 Tool，所以把 `ends_episode=tool.ends_episode` 換成 `ends_episode=(name ==
"done")` 完全不會紅。兩軸 review 各自獨立跑出同一個結果。

**一個例子分不出屬性和拼字，要兩個。** 補了兩條測試：一個**不叫** `done` 但會結束 Episode 的
Tool，和一個**叫** `done` 但不會結束的 Tool。這條在 05/06 把另外八個 Tool 加進來之前尤其
重要 —— 到那時候這個 mutation 會自然變紅，但那是運氣，不是測試。

同一個形狀還出現在別處：`ToolContext` 是 05/06 唯一碰得到機器人的路徑，而在 review 之前
沒有任何測試斷言呼叫端傳進去的 context 真的到得了 handler 手上 —— 把它換成一個當場新建的
空 context 不會紅。

### 15.10 七個 Tool 的數字全部來自 REST reference，而我抄錯過一個（M7 #05）

七個直接 Tool 的每一個 clamp 都對應官方文件裡那個參數自己的範圍，**六個範圍互不相同**：

| 參數 | 範圍 | 來源 |
|---|---|---|
| head pitch | -40（上）～ **26**（下） | REST reference 的 MoveHead 表格 |
| head roll | -40（左）～ 40（右） | 同上 |
| head yaw | -81（右）～ 81（左） | 同上 |
| arm position | -29（上）～ 90（下），degrees | MoveArms |
| LED 各通道 | 0 ～ 255 | ChangeLED |
| volume | 0 ～ 100 | PlayAudio |

`test_every_documented_range_is_its_own` 把這六組**逐一列出來**比對，就是為了讓「整理成一個
共用常數」這種修改變紅 —— 那會讓其中四個變成錯的。

**pitch 我第一版寫 29，是錯的。** 網路搜尋回來的是 29，但 REST reference 的表格寫的是 26，
而且 repo 裡本來就有三處旁證（`tests/test_tools.py` 的 fixture、`legacy/**/CUBS_Misty.py`
把 `pitch=26` 和已知正確的 `yaw=±81` 寫在一起）。Standards 軸抓到的。教訓不是「要查證」，是
**當 in-tree 的既有數字和外部搜尋結果打架時，先假設 in-tree 是對的**——它至少是這個專案某個
人在有機器人的時候寫下的。

§8 的第一條（驅動層只有契約測試、無實機驗證）同樣適用於這些數字：它們是**文件說的**，不是
**硬體做的**。

### 15.11 `display_image` / `play_audio` 收的是語意名稱，不是檔名（M7 #05）

模型送 `happy`、`joy`，Tool 自己去對應 `e_Joy.jpg`、`s_Joy.wav`。理由是自由文字檔名讓模型
可以指名一個機器人上根本沒有的檔案，而失敗會以 driver 裡的一個 404 出現，**Journal 上看不出
為什麼**。enum 進到 schema 之後，模型是在選，不是在猜。

音效只放六個而不是機器人上的六十幾個：把全部塞進 schema 是拿 token 換模型分辨不出來的選項。
**這是刪減，要說清楚是刪減** —— 原本的註解寫成「文件只列了這些」，那是假話，已改。

### 15.12 `speak` 的長度上限是設計決定，所以是常數不是設定（M7 #05）

`SPEECH_MAX_CHARS = 240` 是這七個 Tool 裡**唯一不是**從 reference 來的界限（Misty 沒有記載
上限）。它一開始被我放進 `Settings`，而 review 指出那是 §10 #4 那條：**宣告了卻沒接線比字面值
更糟**。Tool 的參數型別在 import 時就建好，讀不到 per-Episode 的 config，所以那個欄位看起來
可調、實際不可調 —— 而 `look_around` 的 settle **是**從 `ctx.config` 讀的，同一個 config
物件被一個 Tool 尊重、被另一個忽略。

改成模組常數。`look_around_settle_s` 留在 `Settings` 並標 UNCALIBRATED（它是真的未校準：
MoveHead 沒帶 velocity 或 duration，頭實際要多久到位不知道）。

**另外補了一條把 240 這個字面值釘死的測試。** 其他測試都是拿 `SPEECH_MAX_CHARS` 去比，所以
把常數改成 2400 之後測試會跟著一起變寬、照樣綠 —— 和 golden 存在的理由是同一件事。

### 15.13 語音時長估計搬進來了，而它對中文是壞的（M7 #05）

§15.4 說「保留字數估計，把速率常數搬進 config 並明列 UNCALIBRATED」。這件事本來排在 ticket
10，但 **Spec 軸指出那個排法會卡住 07**：golden 2 的 `speak` 結果是
`{"estimated_speech_ms": 1409, "ok": true}`，而 07 的驗收條件是「產出的 Journal 對得上
golden 1、2、3」；ticket 10 又是 **Blocked by 05**，會落在 07 之後。所以 05 交給 07 一個
07 自己不擁有的相依。估計函式因此提前到 05，10 的那條 checkbox 變成已完成。

`estimate_speech_ms("Coming over.", Settings())` = **1409 ms**，與 golden 2 逐位相符 ——
那個 golden 是在這個函式存在之前寫的，所以這是它真的從 §4 的公式推導出來的證據，不是巧合。

**`words / 2.2 + 0.5` 對中文會嚴重低估。** `text.split()` 數的是空白分隔的詞，而一整句中文
是**一個**詞：「你好，我過來一點」估出來是 0.95 秒。這個專案的機器人講中文（`test_journal.py`
的 fixture 就是中文），所以這不是邊角案例。抑制窗開在這個數字上，窗會在 Misty 還在講的時候
就重新打開 —— 也就是 §15.4 要修的那個舊缺陷會以另一種形式回來。**ticket 10 必須處理**，
函式的 docstring 和 `speech_words_per_second` 的描述都指到這一節。

**`SPEECH_MAX_CHARS` 改成推導出來的 150。** 原本的 240 是我隨手挑的，而 §4 的估計在 12 秒
封頂 ——(12.0 - 0.5) × 2.2 ≈ 25 個詞 ≈ 150 字元。超過之後估計就不再跟著文字長度走，`speak`
會回報一個比實際語音短的時長。

### 15.14 `look_around` 差點就該被砍掉（M7 #05）

第一版的 `look_around` 是「掃過三個角度、每個停一下、回正中」。**Spec 軸指出它過不了 §15.2
砍 `back_up` 用的那條測試**：它掃完就回正，所以 ±60° 看到的東西一樣都沒留下 —— 07 附加的
Snapshot 描述的是正前方。回傳的 `looked_at: 4` 數的是「發了幾個指令」，不是「找到了什麼」，
而 `ctx.readings` 明明就在 context 裡、完全沒用。這樣的話，模型連兩個 Turn 呼叫 `move_head`
反而拿到更多（每個角度都有一個真的 Snapshot），這正是「兩個 Tool 做同一件事，模型會挑錯」。

改成**邊轉邊看**：每個角度停下之後讀一次 `latest_reading()`，**找到人就停在那裡**，回傳
`found_at_yaw`；三個角度都沒有才回正並回傳 `None`。停在那裡是關鍵 —— 07 的 Snapshot 是在
Tool 回傳**之後**才附加的，頭要還指著那個人，那個 Snapshot 才會是關於那個人的。掃完回正的
版本會回報「在 -60 找到人」，旁邊擺一張空房間的 Snapshot，同一筆紀錄裡兩個事實互相矛盾。

回傳只有角度。距離和是否看得見都是 Snapshot 的，§15.4 拒絕同一個事實兩份。同理，
`display_image` 與 `play_audio` 原本回傳 `showing` / `played` 把模型自己送的參數又抄一遍 ——
那些已經在 04 寫的 `tool_called.args` 上了，已移除。

### 15.15 「表現力靠組合」在目前的 Turn 上限下付不起（M7 #05，**未決**）

Spec 軸算的：舊腳本的 `wave` 是 `move_arms` 四次加一次回正 = **5 個 Turn**，而
`config.max_react_steps` 預設就是 **5**。也就是說在預設值下，模型揮一次手就用完整個
Episode，做不了別的 —— §4 說 AutoMisty 移除後表現力由組合取代，而這個上限讓組合付不起。

**這裡不改。** 上限的語意（它數的是 Turn 不是 Step）和它的值都是 ticket 07 的範圍，而且改值
要有依據，不是挑一個更大的數字。記在這裡，07 必須做這個決定並寫下理由。

另外：`fear` 改叫 `afraid`（舊腳本用 `fear`）。純粹因為模型送的是形容詞，其他六個也都是
（`happy`、`sad`、`angry`、`surprised`、`love`、`neutral`），混用名詞會讓 enum 讀起來不一致。

### 15.16 拒絕理由也會洩漏，而 `_screen` 到不了它（M7 #06 review）

Spec 軸發現：模型送 `{"linearVelocity": 0.5, "timeMs": 800}` 給 `approach`，dispatch 產生的
拒絕理由是 `"linearVelocity, timeMs: not an argument 'approach' takes"` —— 這句話會寫進
`ToolRejected` 紀錄，並在 07 變成模型讀到的 Observation。

`journal.py` 的 `_screen` 守的是 `ToolCalled.args` 和 `Observation.result`，**兩個都是
mapping**。`ToolRejected.reason` 是一個句子，`_screen` 根本到不了。spec 那句「velocity 與
timeMs 也不出現在送給模型的任何文字裡」因此是破的 —— 而且破在最尷尬的地方：**Journal 正是
一個讀者用來檢查 §4 分層主張的東西**。

兩層修法：

1. `layering.mentions_control_parameter(text)` —— 把句子切成字，逐字問 `control_parameter`。
   `ToolRejected.__post_init__` 用它擋下來，所以這種紀錄**建不出來**。
2. dispatch 遇到未知參數時，是控制參數的就**描述而不是複述**：「a physical control parameter,
   which is the control layer's」。模型不需要那個拼法，只需要理由。

**必須逐字切，不能整句丟進去。** 整句丟進去剛好會抓到 `linearVelocity`（速率 stem 是子字串
比對，出現在哪裡都算），但**每一個時間單位都會漏** —— 時間規則看的是最後一段，而一個句子的
最後一段是句子的最後一個字。`drive_ms: not an argument...` 整句丟進去回傳 None。這條是
mutation 才逼出來的。

### 15.17 我把一個「等價變異」判斷錯了（M7 #06 review）

`approach` Tool 回傳 `outcome.status.value`。我跑的 mutation 把它換成 `outcome.status`
（enum 本身），整套測試照樣綠，於是我判定那是**等價變異**（equivalent mutant）並寫進紀錄 ——
理由是 `ApproachStatus(str, Enum)`，`json.dumps` 出來一模一樣，`from_jsonl` 往返也相等。

**Standards 軸指出那不等價。** Python 3.11 的 mixin enum，`__str__` / `__format__` **不是**
value：`f"{ApproachStatus.ARRIVED}"` 得到 `"ApproachStatus.ARRIVED"`。而 `journal.py` 的
`TerminalRenderer` 就是用 f-string 印 `record.result.get("result", "")` —— §4 把那個 renderer
算成 Journal 的一等訂閱者。所以那是**一個 Journal 的讀者被騙**，不是無害的型別差異。

我驗證了序列化和比較，**沒有驗證顯示**。教訓：宣稱等價，要把該型別所有的出口都走過一遍，
不是走過自己想得到的那幾個。測試補在 `_describe()` 上。

### 15.18 「薄轉接」要證明的是它**沒有**加東西（M7 #06）

`approach` Tool 是六行：呼叫 M5 的閉環，把四個狀態原封不動傳回。難的是證明它真的什麼都沒加。

`test_the_tool_says_exactly_what_the_backend_said` 的第一版 docstring 寫「任何規劃、重試或
平滑化都會在這裡顯示出來」—— **它看不到重試**。因為所有的 double 都是決定性的，重試第二次會
得到和第一次一樣的答案，兩邊照樣相等。這正是 §15.9 那條：docstring 斷言了它的測試檢查不到的
事。已改成說清楚它抓得到什麼（改名、壓縮、增刪 key）、抓不到什麼，並另外用一個**第一次失敗、
第二次成功**的 double 去抓重試。

同理，「Tool 沒有自己的 try/except」也需要一個從 `run_approach` **外面**來的失敗才測得到 ——
`approach()` 自己會把機器人的例外接成 `drive_error`，所以包在外面的 try/except 在所有正常
情境下根本不會被觸發。ticket 08 的緊急停止正是那種從外面來的失敗，所以這條是 08 的前提。

**`ToolContext.config` 是 None 時要當場說清楚。** `run_approach(config=None)` 會讓
`approach()` 自己那個能用的預設值失效，然後在控制層裡拋一個 `AttributeError: 'NoneType'`，
訊息裡既沒有 Tool 名字也沒有欄位名字。這是 §10 #4 換一層出現。

### 15.19 Turn 上限改名，並定為 8 —— 下界是推導出來的，不是挑的（M7 #07）

**改名先說：** `max_react_steps` → `max_turns_per_episode`。它的舊名字用 `steps`，而它自己的
描述寫的是「Hard cap on LLM **turns**」；`CONTEXT.md` 的 `Step` 是控制層的一次驅動命令，
`Turn` 才是 ReAct 的一輪。改名時只有一個呼叫端（`tests/test_goldens.py`），成本接近零。

**值定為 8。** §15.15 記下的問題是：舊腳本揮一次手要好幾個 Turn，而上限預設就是 5，
§4 說「表現力靠組合」在那個上限下付不起。§15.15 指名由這張票決定，而且**要有依據**。

依據是舊腳本自己的手勢。`full_robot_v3.py` 的 `_do_gesture("wave")` 展開成 **6 個原始命令**
（兩輪各兩次 `move_arms`，加上 `move_arms` 回正、`move_head` 回正）。§4 主張 AutoMisty 移除
後這種表現力由模型組合原始 Tool 取代 —— 那麼上限至少要讓它**做得到它取代的那件事，並且還能
說一句話、還能自己結束**：6 + 1 (`speak`) + 1 (`done`) = **8**。

這是**下界**，不是量出來的最佳值。這張票的敘述本來就說「上限值是初值，之後用 Journal 的資料
修正」，`max_turns_per_episode` 的描述也照樣寫著要從 Journal 資料修正。改的是它現在有個站得住
的下界，而不是一個沒來由的 5。

**代價：golden 3 要跟著長到 8 個 Turn。** `test_the_turn_limit_golden_stops_at_the_configured_cap`
（ticket 03 寫的）就是為了讓「改上限」不能默默讓那個 golden 失效。延長時沿用檔案自己的算術
規律（latency +11ms、tokens_in +40、距離 −1），不是隨手填。

### 15.20 Step 計數放在 `Dispatched` 上，不讓迴圈去撈字串鍵（M7 #07）

ticket 04 的 review 留下的問題：`episode_finished.steps` 是實際驅動次數的總和，而 `approach`
的次數只在 `result["steps"]` 這個字串鍵裡。兩個選項，選了後者：

1. 迴圈自己 `result.get("steps", 0)` —— 迴圈就得知道哪些 Tool 會驅動、以及它們把次數叫什麼。
2. **`dispatch` 讀那個鍵，`Dispatched` 給迴圈一個型別化的 `steps` 欄位。**

選 2 的理由是分層：迴圈不該知道 Tool 結果的形狀。字串只出現在 `tools.py` 的 `STEPS_KEY`
一處，而且 `_steps_in()` 會拒絕負數、布林和非整數 —— 那個數字會進 `episode_finished.steps`，
golden 斷言它是真的發生過的驅動次數，所以一個 `True` 悄悄被當成 1 是有後果的。

### 15.21 golden 的 `t` 讓步：時間只在真的等待時前進（M7 #07）

**先說結論：goldens 1 與 2 的每一個非時間欄位，迴圈都逐一對上了** —— 包含 ticket 04 讓步
產出的拒絕理由（`"pitch 140 is outside the permitted range"`）與 ticket 05 的
`estimated_speech_ms: 1409`。唯一對不上的是 `t`。

原因很具體。golden 的 `t` 手寫時帶了看起來合理的簿記成本：`episode_started` 到
`turn_started` 是 4ms，`model_called` 到 `tool_called` 是 2ms，等等。但 spec §125–127 指定
沿用 `approach()` 既有的 `Clock` protocol 與假時鐘，而**那個假時鐘只在 `sleep()` 時前進**。
dispatch 不 sleep、寫紀錄不 sleep，所以那些 2ms/4ms 在確定性的執行下**一律是 0**。

三個選項：讓迴圈為了對上 golden 去 sleep 2ms（荒謬，而且會讓正式執行變慢）；讓假時鐘每次讀
就前進一格（湊不出來 —— `EpisodeClock` 的原點是第一次讀，`episode_started` 就不可能是 0.0，
而且那會變成 golden 在測假時鐘而不是測迴圈）；**或讓 golden 的 `t` 讓步**。

選第三個。新規則寫進 `tests/goldens/README.md`：

> **`t` 只在真的有等待時前進** —— 一次模型呼叫，或一個會 sleep 的 Tool。迴圈連續寫下的
> 紀錄共用同一個時間戳，因為在注入時鐘之下它們之間確實沒有時間流過。

這條規則讓每一個 `t` 仍然**可以用檔案自己的數字手算驗證**（`latency_ms` 加上 Tool 的等待
時間），所以「golden 由 spec 推導」這個性質保住了。

**⚠️ 補跑 review 的更正（2026-09-05）：上面「讓步的是那些簿記成本」說得太輕，而且有一處在
當時根本還沒有理由。** 逐欄位比對之後實際變動是：

| | 原本 | 現在 | 那是什麼 |
|---|---|---|---|
| golden 1、3 各處 | 2–4ms | 0 | 確實只是簿記成本 |
| golden 2 `speak` → `observation` | **1409ms** | **0** | 不是簿記。那是整段語音時長從時間軸上消失，因為 `speak` 不再 sleep —— 而那個決定是 **§15.29，晚三個 commit 才在 #10 做的** |
| golden 4 `tool_called` → `stop_requested` | **3.585s** | **0.014s** | 中止從「驅動進行中」移到「第一次驅動剛下完」 |

前兩者現在都有理由（§15.29 補上了 `speak` 的），但**寫 §15.21 的時候沒有**，而我把它們一起
歸類成「2ms 簿記」。欄位層級上「差異只有 t」是真的，作為描述則是誤導。

**而且我拿來當證據的那個數字，證不了我說的事。** 我寫「ticket 03 的六十條內容斷言 59 條通過，
所以改動保住了意義」—— 但 `test_goldens.py` 裡碰 `t` 的五條全部是**關係性**的（單調遞增、
在 stop 之後、最後一筆晚於 stop），沒有一條碰絕對值，也沒有任何一條碰 `look_around` 的結果。
**那個 59/60 對這幾種改動天生免疫**，通過與否跟改動保不保住意義無關。真正檢查那些改動的是
逐欄位的 diff，不是那個統計。

**這削弱了 spec §126 的「逐字元比對」說法**，要說清楚：現在能主張的是「結構與所有非時間欄位
逐一相符，`t` 由一條可手算的規則決定」。相鄰紀錄共用時間戳是這條規則的直接後果，不是缺陷 ——
注入時鐘之下它們之間就是沒有時間。

**golden 4（中止）不在這張票裡動。** 它有 `stop_requested`，要 ticket 08 才產得出來，
而改一個自己驗證不了的 golden 比放著更糟。08 要把它帶到同一條規則上，README 已註明。

### 15.22 `look_around` 的結果讓 §15.14 贏（M7 #07）

golden 3 的 `look_around` 結果是 `{"ok": true}`，而 §15.14 在 ticket 05 的 review 之後把它
改成邊轉邊看、回傳 `found_at_yaw`。golden 寫在那個改動之前。

**golden 讓步。** §15.14 是有記錄、有理由的設計決定（掃完回正的版本過不了 §15.2 砍 `back_up`
用的那條測試），而 golden 3 那筆 `{"ok": true}` 反映的是被那次 review 推翻的舊形狀。順帶一個
自身一致性問題也修掉了：golden 3 的 Snapshot 寫 `face_present: true`，那麼同一個 Turn 裡的
`look_around` 本來就該找到人 —— 舊的 `{"ok": true}` 對這件事一個字都沒說。

### 15.23 兩軸 review 這次跑不起來，我自己補做（M7 #07）

subagent 連續四次 529（server overloaded），兩軸都起不來。不等了，兩軸的工作我自己做，
**並且把「這次沒有第二雙眼睛」寫在這裡**，因為前六張票每一張都是 review 抓到我看不到的東西。

自己跑的 Standards 電池（十三個，刻意挑我第一輪沒想到的）**存活六個**，全部是真的漏洞：

| 存活的 mutation | 為什麼會活 |
|---|---|
| `as_text` 回傳 `""` | **最嚴重的一個。** 分層測試（模型收到的文字不含 velocity）整個建在 `as_text` 上，它回空字串的話那條測試在任何實作下都會綠。 |
| `_observed` 把 `distance_cm` 寫成 None | 沒有任何測試斷言 Snapshot 的值真的到得了模型手上 —— 只斷言了它進得了 Journal。 |
| 模型送出的決定完全不進 working context | 模型看不到自己上一輪要求了什麼，就分不出「拒絕」和「別的事的回答」。 |
| trigger 不進 working context | 第一個 Turn 變成對著空氣做決定。 |
| working context 以可變 list 交出去 | 模型那一側是不可信的一側，交出活的 list 等於讓它改寫歷史而 Journal 看不出來。 |
| 寫第二筆 `EpisodeFinished` | **這個是真的等價變異** —— `Journal.record` 本來就拒絕，我**實測驗證過**（§15.17 的教訓），不是假設。 |

共同原因很清楚：**我的斷言幾乎全都指著 Journal，而 Journal 可以是對的、同時模型什麼有用的
資訊都沒收到。** Journal 是交付物，但它不是唯一的出口。補了九條指著 working context 的測試
之後 12/13 紅（剩下那個是已驗證的等價變異）。

**Spec 軸自己做的部分：golden 的改動逐欄位盤點過。** goldens 1、2 只有 `t` 變；golden 3 是
`t` 加 `found_at_yaw` 加延長 3 個 Turn；golden 4 沒動。沒有夾帶任何內容修改。

**59/60 這個數字也實測了**：把**原始** golden 放回去跑 ticket 03 的六十條內容斷言，59 條通過，
唯一失敗的是 `test_the_turn_limit_golden_stops_at_the_configured_cap` —— 也就是那條專門用來
讓「改上限」不能默默失效的測試，正在做它該做的事。新 golden 則是 60/60。

**`instructions=` 參數移除。** 它接線了、但零測試零呼叫端，是 Speculative Generality，而
ticket 09（memory 重新設計，§15.5）才是決定 working context 裡還該有什麼的那張票。

**`.env.example` 已經過期兩層**（`MISTY_MAX_REACT_STEPS` 在「DECLARED BUT NOT YET WIRED」
區塊裡，而迴圈已經落地、名字也改了）。它是四個受保護檔案之一，**只標記不修改**。

### 15.24 緊急停止：記錄的時間是它發生的時間，而且 halt 失敗不能連終止保證一起賠掉（M7 #08）

`misty_agent/agent/stop.py`。三個決定：

**順序是「先記錄，後 halt」。** 時間戳必須是腳踩到保險桿的時間，而 halt 是一次 HTTP 往返 ——
先 halt 就會把機器人的回應時間折進一個本來要量「我們有多快」的數字裡。`stop_requested` 與
`episode_finished` 分成兩筆紀錄的理由（§15.3）就是那個差距，也就是中斷延遲。這也是 ticket 02
當初選「加鎖直接寫」而不是「丟佇列讓迴圈去撈」的原因：**寫紀錄的是那條踩下去的執行緒本身**。

**用 `POST /halt` 不用 `POST /drive/stop`。** 後者只停底盤，會留一隻手臂停在半空 —— 有人把腳
放在保險桿上的時候，「沒有留下未停止的動作」不是這個意思。

**halt 失敗時例外要吞掉。** 這是整個專案唯一一處「吞例外是對的」：它跑在感測器的執行緒上，
沒有人會接；而 Episode 還是得結束。**一個沒停下來的 halt 很糟，一個沒停下來、Episode 還繼續
跑的 halt 更糟。** `halted` 欄位誠實記錄它到底成不成功，而 §8 的老實話照樣適用：沒有硬體，
無法主張馬達真的停了，能主張的是那個請求先發出去了。

**迴圈檢查兩次，而且是兩件不同的事。** dispatch 之前那次拒絕**開始**一個新的物理動作；
Observation 之後那次在已經在跑的動作回傳之後結束 Episode。golden 4 走的是第二條。

### 15.25 那條 race 測試原本測不到 race（M7 #08）

「多執行緒同時踩，只能產生一個 stop」第一版是八條執行緒卡在 barrier 上然後一起衝 ——
**測不到**。把 `request()` 的鎖整個拿掉，那條測試照樣綠；把 `sys.setswitchinterval` 降到 1ns
也照樣綠。因為 `if self._source is not None` 到 `self._source = source` 之間的視窗在 GIL 下
太窄，barrier 放行本身又是序列化的。

改用 `threading.settrace` 掛一個「每一行都 `time.sleep(0)`」的 hook，把 GIL 在每個 bytecode
之間交出去。這樣視窗就夠寬了：無鎖版本會出現**兩個贏家、兩筆 `stop_requested`**，有鎖版本
永遠是一個。實測兩邊都跑過才寫進去的。

這是 M7 #02 那個教訓的第二次出現 —— 當時「時間戳在鎖之前取」那條測試也是名義上在測並行、
實際上把鎖拿掉還是綠。**併發的測試要先證明它抓得到那個 bug，再相信它。**

### 15.26 Memory：只增不改，衍生物在 Episode 邊界重算（M7 #09）

`misty_agent/agent/memory.py`。§15.5 的設計落地，三個地方與舊版不同：

**折疊不刪除。** 舊版的 `short_term` 是一個 deque，溢位就把最舊的 pop 掉丟給摘要 —— 摘要漏了
什麼，原文就永久沒了。新版 `_folded` 只是一個**讀取位置**，Exchange 全部留著。這也讓「重載
後仍在」順便涵蓋了 Exchange 原文，不只是 facts。

**「最近幾輪」是純函式切片。** 不呼叫模型、不碰 I/O。§14.6 欠的五條檢查裡，視窗上限與
prompt block 這兩條因此可以在微秒內跑完，而且**建構 Memory 時 summariser 與 extractor
都傳 None 也測得動** —— 那是「它真的沒碰模型」最強的證明形式。

**衍生在 Episode 邊界做一次。** `close_episode()` 是唯一呼叫模型的地方。ReAct 之下一個
Episode 有多個 Turn 但使用者只說了一次話，舊版每輪抽取是在對著沒有新東西的紀錄付一次模型
呼叫與它的延遲。**這條只能在迴圈層級證明** —— memory 自己看不出「某個 Turn 沒有觸發它」，
所以 `test_a_long_episode_derives_memory_exactly_once` 跑滿八個 Turn 然後斷言 extractor
被呼叫一次。

**兩個衍生都不能把 Episode 一起帶走。** summariser 失敗就退回粗暴的截斷串接（絕不整批丟
失），extractor 失敗就什麼都不更新。**一份過時的摘要是比較差的記憶；一個因為摘要逾時而
消失的互動是比較差的機器人。**

**`close_episode()` 在 `EpisodeFinished` 之後才跑。** 摘要可能是一次模型呼叫，折進 Episode
的時間裡會讓每一次延遲量測都包含沒有人在等的工作 —— 而且會移動 `episode_finished.t`，
那是四個 golden 釘住的東西。

**存檔是先寫暫存檔再 rename。** 這個 process 可能被一隻腳打斷（`stop.py`），而**昨天的記憶
救得回來，今天的一半救不回來**。

### 15.27 「說了什麼」由 Tool 自己宣告，迴圈不去猜（M7 #09）

Exchange 的另一半是「機器人回了什麼」。迴圈要拿到它，兩條路：

1. 迴圈自己看 `decision.args["text"]` —— 那是 §15.20 拒絕過的字串鍵耦合，而且迴圈得知道
   那個 Tool 叫 `speak`。
2. **registry 宣告**：`@registry.tool("speak", ..., speaks="text")`，`dispatch` 從**驗證後**
   的參數取值放進 `Dispatched.spoken`。

選 2，理由與 `ends_episode` 是同一條（§15.9）：**推斷出來的性質會在名字改變的那天默默失效**，
而 memory 會停止記錄卻沒有任何測試變紅。註冊時會檢查 `speaks` 指的欄位真的存在。

拿驗證後的值而不是原始請求，是為了「記下來的就是講出去的」—— `speak` 的參數型別會 strip，
兩者在有前後空白時不一樣。

**沒有把它放進 Tool 的結果裡**，因為 §15.4 拒絕 Observation 重複參數 —— #05 的 review 就是
為了這條把 `said` / `showing` / `played` 拿掉的。

### 15.28 語音時長估計：兩種文字，兩個速率（M7 #10）

§15.13 記下的缺陷：`words / 2.2 + 0.5` 數的是空白分隔的詞，而**一整句中文只有一個**。
「你好，我過來一點」估出來 0.95 秒 —— 抑制窗開在這個數字上，會在 Misty 還在講的時候就重新
打開，然後她把自己講的話轉錄進來。**這正是 ticket 10 要修的舊缺陷，換一條路回來。**

改成兩個速率相加：CJK 字元用 `speech_cjk_chars_per_second`（預設 5，UNCALIBRATED），
其餘用原本的詞速率。**CJK 字元在數詞之前先被移除**，否則一句沒有空白的中文會同時被算成
一個拉丁詞。涵蓋 CJK 標點、假名、韓文，因為三者都不用空白斷詞。

「你好，我過來一點」現在是 2100ms。**`"Coming over."` 仍然是 1409ms** —— 四個 golden 建在
那個數字上，而拉丁文字完全不受這條規則影響。

**一條原本抓不到這個 mutation 的測試。** 我寫的「混合文字各算一次」比較的是
`估計("你好我過來 Ana") - 估計("你好我過來")`，而「CJK 也當成詞」這個 mutation 讓**兩邊都**
多算一個詞，差值不變 —— 照樣綠。改成拿純 CJK 字串去比對**絕對值**（字數 ÷ 速率 + overhead）
才抓得到。同一個形狀第二次出現在這個專案裡：**比較兩個數字的差，看不到同時影響兩者的錯誤。**

### 15.29 抑制窗只蓋播放，而且在送出請求之前就關上（M7 #10）

**只蓋播放。** 舊腳本是 `mute_for(spoken_s)` **然後 `time.sleep(spoken_s)`** —— 整段動作期間
都聾了，使用者在機器人講話時說的任何話（包括「停」）整段消失。新版只 mute 不 sleep，所以窗
一過就聽得見插話。有一條測試直接斷言 `clock.slept == []`。

**在 `POST /tts/speak` 送出之前就關上。** 那是一次往返，Misty 在另一端才開始講；送出之後才
mute 會留下一段她聽得見自己開口的空隙。測試用一個會在 `speak()` 被呼叫時檢查「麥克風關了沒」
的假機器人釘住這個順序。

**`AudioStream` 的時鐘改成可注入。** 原本三處直接呼叫 `time.monotonic()`。用等兩秒去測一個
兩秒的窗，會做出一套又慢、而且在忙碌機器上還會錯的測試 —— 「窗內」與「窗後」現在是兩個斷言，
不是兩次 sleep。

**`mute_for` 的截止時間取 max 不是覆寫**：兩段重疊的語音應該在**較晚**那段結束時開窗，不是
在兩段長度相加之後。

沒有任何程式碼再去找 `spoken_ms` —— 有一條測試掃過整個 `misty_agent/` 確認這件事。

### 15.30 折疊與視窗重疊：一個在**預設值**下就成立的缺陷（07–10 補跑 review）

`Memory._fold` 原本的條件是「未折疊數 > window 就折 `fold_size` 筆」。在出廠預設
`window=6, fold_size=3` 之下，第 7 筆之後：摘要蓋住 said1–3，而 `[Recently]` 仍然逐字印出
said2–said7 —— **模型在同一份 prompt 裡把同兩筆讀了兩次**，正是 §15.4 拒絕的事，而且是我
自己寫在 `fold_size > window` 那道防護的 docstring 裡宣稱不可能發生的事。

改成只折**真的掉出視窗**的那些：`foldable = len(exchanges) - window - folded`，一次最多折
`fold_size` 筆。`fold_size` 因此是**批次上限**而不是固定筆數。原本那道 `fold_size > window`
的防護解決不了問題（重疊在任何 `fold_size > 1` 都會發生），換成 `fold_size >= 1`。

**為什麼沒被抓到：沒有任何一條測試用 `fold_size > 1` 折過 —— 而 3 就是預設值。**
`fold_size=2` 只出現在「斷言不會折」的測試裡，`3` 只出現在那條 ValueError 測試裡。所以
`_folded += len(batch)` 換成 `+= 1` 也照樣全綠。現在有一條 parametrize 過 `(6,3) (6,1)
(2,2) (4,3)`、逐筆檢查重疊的測試，外加一條「掉出視窗的最後都會被摘要」的陰性對照。

### 15.31 補跑 07–10 的兩軸 review：一次就成功了（2026-09-05）

**§15.23 說「subagent 連續四次 529，兩軸都起不來」—— 那是 #07 當下的事實。問題是我把它當成
一個持續狀態，在 #08、#09、#10 三張票的 Comments 裡都寫「兩軸仍然跑不起來」，而我一次都沒有
再試。** 隔天補跑，兩軸同時起來，一次就成功。三張票的措辭已更正為「沒有跑，因為我沿用了推測」。

**推測寫成事實**，而且寫進了三份交付紀錄 —— 這正是這個專案在別的地方一直在防的那種錯誤
（§15.17 的等價變異、§15.21 的「差異只有 t」）。教訓一樣：**沒查證的狀態不要寫成事實，
尤其是那種一次重試就能查證的。**

補跑抓到的東西證明這件事是有代價的：一個**預設值下就成立**的 prompt 重複缺陷（§15.30）、
一個把全形拉丁字母當成音節的正規表達式、一條會把全形 `Ｈｅｌｌｏ　ｗｏｒｌｄ` 估成 2.7 秒的
路徑、`CONTEXT.md` 裡一個已經不存在的設定名、以及 §15.21 那段誤導性的描述。這些都是四張票
自審沒看見的。

### 15.32 真模型測試：不變量當 gate，行為只報告（M7 #11）

根目錄那份 `test_llm_live.py` 呼叫真模型、印出每個決策與硬體呼叫、**零斷言** —— 它證明不了
任何事，也進不了 CI。刪除，換成 `tests/test_llm_live.py`（掛 `llm_live` marker、預設排除）。

**gate 的是不變量，不是模型講了什麼。** 七條檢查放在 `tests/episode_invariants.py`：
Episode 一定結束一次、Turn 上限成立、模型沒收到物理參數、Tool 參數都在範圍內、每一次驅動
都來自控制器、Journal 寫得下也讀得回、被拒絕的呼叫不會同時算成成功。模型**選了什麼**不是
gate —— 先看一圈再回話的模型不是 bug —— 那些另外計數、印成通過率。

**marker 註冊在 `pytest.ini`。** `tests/conftest.py` 是受保護檔案不能改；`pyproject.toml`
會讓這個沒有打包設定的 repo 看起來像要打包。`addopts = -m "not llm_live"` 讓預設執行**排除**
而不是 **skip** —— M6 #08 示範過 skip 會怎麼侵蝕「全綠零 skip」。有測試直接讀 `pytest.ini`
釘住這兩行，因為刪掉任何一行都是無聲的：live 測試會開始跑，第一個發現的人是帳單。

**每條 gate 都在離線證明過會紅**（`tests/test_episode_invariants.py`）。這是關鍵：一條空洞的
檢查在一套沒人跑的付費測試裡會永遠綠，而那正是這張票要終結的「印出來給人看」。

### 15.33 那套付費測試的兩個坑，都是 review 抓到的（M7 #11）

**一、`approach` 的檢查在 live 是空的。** 我給 live 用的 reading source 把
`frame_arrived_at` 標成 0.0，而注入時鐘也在 0.0 —— 每一筆讀數都是過期的，`approach` 永遠
回 `lost_user`、0 個 Step，於是「每次驅動都來自控制器」永遠只是在比 `0 == 0`。**離線有牙齒、
上線沒有**，而那是最糟的位置。改用 M5 驗證時的同一個 `MovingWorld`，並補一條
「至少有一個情境真的動了」當陰性對照。

**二、沒有 key 時的訊息叫人去做一件沒有用的事。** 我寫「把 key 放進專案的 `.env`」——
`Settings` 只讀 `.env` 裡 `MISTY_` 開頭的欄位，而且**從不匯出到環境變數**，而
`api_key_available()` 讀的是環境變數。`.env.example` 第 6 行本來就寫著「不要把 OpenAI key
放這裡」。更糟的是我寫了一條 `assert ".env" in message` 把錯誤建議**鎖了起來**。正確答案是
`export OPENAI_API_KEY=sk-...`，而且補了一條測試實際建一個 `.env` 去證明它真的沒用。

**成本也順手砍半。** 行為報告原本把三個情境**再跑一次**，58 次模型呼叫裡有 24 次只是為了印
一份報告。改成共用 gate 已經跑過的 Episode，worst case 58 → **34 次**（約 0.09 美元）。

**還有一條 §15.20 的違規是我自己犯的**：`every_drive_came_from_approach` 又去挖
`result["steps"]` 這個字串鍵 —— 而 §15.20 正是為了「不要再有人去挖它」才把它收進
`tools.py` 的 `STEPS_KEY` 並給出型別化的欄位。改用 `EpisodeFinished.steps`。

**以及一份「第二意見」清單其實是有損的拷貝。** `FORBIDDEN_IN_PROMPT` 刻意不從 `layering.py`
import（審計者共用被審計者的定義就沒有意義了），但第一版漏了 `speed`、`driveSpeed`、
`cmPerSec`、`driveDuration`，而且 `cm_per_sec` 用底線寫、`layering.py` 卻會正規化 camelCase
—— 也就是 Misty API 真正用的那個拼法會溜過去。§10 的「兩份拷貝會默默分歧」發生在那個專門
用來抓這件事的檔案裡。改成先攤平再比對，並加一條 meta 測試斷言它**至少和守衛一樣嚴**。

### 15.34 舊主腳本刪除，入口換成 `misty_agent/app.py`（M7 #12）

`full_robot_v3.py` 從 M5 起就是唯讀參考（§12.3），留著只是因為 prompt 與 memory 還沒搬出來。
M7 做完之後它沒有理由存在，而**留著一份「看起來能跑但沒人維護」的完整實作，是下一個接手的人
最容易誤用的東西**。

**分成兩支 commit。** 票面要求刪除的 diff 不要混在其他改動裡 —— 一千多行的刪除混著改動，
review 看不出刪掉的是不是正確的東西（M6 #02 刪舊 runner 時就是這樣做的，那次也確實靠 review
抓到漏改）。所以：先一支只加入口，再一支只刪。

**入口是「一個觸發，一次 Episode」**，不做外層迴圈 —— §15.1 的理由沒有改變：外層依賴
`AudioStream`，而它的轉錄與 VAD 擠在同一條 thread 上是 HANDOFF §4 記著的未修缺陷。

**這裡才是 M7 兩個「造好卻沒接線」的機制第一次有生產呼叫端**：`EmergencyStop` 與
`ToolContext.ears`。兩個都完整測過、完全沒接上 —— 一個忘記接線的 session 會通過專案裡其他
每一條測試，同時讓機器人停不下來、而且對自己的聲音充耳不聞。寫測試時抓到我自己的兩個接線
bug：`ears` 預設 `None` 會讓 `speak` 炸掉（#11 拿掉了 `None` 檢查改用空物件），以及同一秒內
的兩個 Episode 會共用 id。

**保險桿訂閱一次並保持存活**，因為在兩個 Episode 之間踩下去的人一樣是認真的：那時沒有東西可
記錄、沒有 Episode 可中止，但馬達一樣是真的，所以兩種情況都會 halt。Episode 進行中則走那個
Episode 自己的 `EmergencyStop`。**單一個長命的 `EmergencyStop` 做不到** —— 它設計上是一次性
的（§15.24），第二次踩就會被吞掉，而且它在建構時就綁死一個 Journal。

**一個時鐘交給四個協作者。** `Journal`、`run_episode`、`approach`、`AudioStream` 各自預設用
自己的 `time.monotonic`。不統一的話，Episode 的時間戳、量到的模型延遲與抑制窗來自四個**剛好
一致**的時鐘，而沒有任何測試說得出差別。

**`OAI_CONFIG_LIST.json` 的讀取搬進入口而不是砍掉。** 那段程式只存在於被刪的檔案裡，而
`.env.example`（受保護檔案，不能改）與 README 都還在承諾這個管道 —— 砍掉會讓一個我改不到的
檔案說謊。環境變數優先於檔案：明確 `export` 的東西不該被一個別人忘記的檔案默默蓋掉。

**README 的 Project structure 原本列了六個不存在的檔案**（`AutoMisty.py`、`Agents/`、
`CUBS_Misty.py`、`RobotCommands.py`、`code/mistyPy/`、`Mistydemo/`），它們在 M1 就移出版控了。
票面只要求更新指向舊主腳本的指涉，但那整塊已經是現況描述而且大半是錯的，一併修正。

### 15.35 M7 closure：失敗也是一種有界結束，bumper 在 Session 建構時上膛（M7 #13）

M7 #12 完成後重新從 code 而不是勾選稽核，找到兩個會讓「每個 Episode 有界結束」只在 happy
path 成立的洞：模型、直接 Tool 或 Snapshot 拋例外時，`run_episode()` 直接把例外丟出去，Journal
停在半途；而 bumper 雖然已有 production wiring，呼叫端仍必須另外記得呼叫
`Session.watch_the_bumper()`。兩者都能讓票面全綠、實際保證不成立。

**失敗路徑現在也是公開結果。** `EpisodeFinished.outcome` 增加 `error`；失敗原因先寫成一筆
非 terminal 的 `execution_failed`，帶 `phase`、例外型別與可安全公開的訊息，最後仍由唯一一筆
`episode_finished` 關閉。模型、Tool handler／result、Snapshot 與 Episode 開始時讀 Memory 的
失敗都走這條路，並在結束前 best-effort 呼叫 `halt()`；halt 自己失敗不得連終止保證一起賠掉。
例外訊息若含控制參數名稱會被隱去，因為 Journal 仍是 §4 分層主張的稽核標的。

Memory 的摘要／事實衍生依 §15.26 發生在 `episode_finished` **之後**，所以它失敗時不回頭改寫
已完成 Episode 的 outcome；它會留下 error log，但公開呼叫仍拿得到已完成的 outcome 與 Journal。

**bumper 不再靠第二個動作上膛。** 傳入 event stream 的 `Session` 在 `__post_init__` 就訂閱，
`watch_the_bumper()` 保留為冪等的 lifecycle 操作：重複呼叫不開第二條 websocket。沒有 event
stream 的 mock／測試 Session 行為不變。訂閱名稱屬於 Session 而不是全域固定字串，因此兩個
Session 共用同一個 EventStream 時，各自都有自己的 callback，不會讓第二個 Session 表面建構
成功、實際卻仍由第一個 Session 接收緊急停止；若 event stream 沒有建立訂閱，Session 建構直接
失敗，不留下「可執行 Episode 但沒有 e-stop」的半接線物件。

`error` 成為新的 outcome 後也新增第五份 golden；既有四份保持逐位元不變。這保留 spec
「每一種結束方式都有對照」的原始約束，而不是把 error 排除後讓測試變綠。

這仍然只有契約測試與 fake robot 驗證。`halt` 請求是否真的停住 Misty、bumper websocket 是否
符合實機行為，仍屬 §8 的未驗證邊界。

### 15.35 保險桿在 Episode 剛結束的空隙被踩下去，什麼都不會發生（M7 #12 補跑 review）

`Session.bumper_pressed` 原本長這樣：

```python
running = self._running
if running is not None:
    running.request("foot_bumper")   # ← try 之外
    return
try:
    self.robot.halt()
except Exception:
    pass
```

`EmergencyStop.request()` 會往 Journal 寫一筆 `stop_requested`，而**已經結束的 Journal 拒絕
任何紀錄**（那是 §15.24 刻意要的性質：「一個 Episode 只結束一次」要能用數的）。所以在
Episode 收尾之後、`_running` 被清掉之前踩保險桿 → `ValueError` 從 `request()` 拋出來 →
`except` 包不到它 → **沒有紀錄、也沒有 halt**。

**那個空隙不是幾微秒。** `react.py` 記完 `EpisodeFinished` 之後還要做 `memory.remember()` 和
`memory.close_episode()`，而 `close_episode()` **會呼叫模型**（§15.26 刻意把它排在結束之後，
理由是不要把沒人在等的工作折進延遲量測裡）。要等那趟網路來回結束、`run_episode` 回傳，
`Session.episode` 的 `finally` 才清掉 `_running`。**整個記憶整理階段踩保險桿，機器人不會停。**

修法是讓它**掉下去**而不是回傳：Journal 拒絕紀錄是對的，但馬達不在乎紀錄寫到哪裡去了。

**測試走真實順序，不用手去設 `_running`** —— 順序本身就是那個 bug。用一個會在 `extract()`
裡踩保險桿的 extractor，那正好落在窗內。

**一個經過驗證的等價變異**：把 `finally: self._running = None` 拿掉，測試全綠。這次不是測試
沒牙齒 —— `_running` 是 `None` 就直接去 halt，是過期的 stop 就 `request()` 拋例外、掉下去、
一樣 halt，**兩條路可觀察的結果完全相同**。清掉仍然是對的衛生習慣，但它現在沒有可觀察的後果。
（§15.17 的教訓：宣稱等價要先驗證。這次跑過了。）

**順帶補強一條原本測不到東西的測試。** `test_pressing_the_bumper_between_episodes_still_halts_the_robot`
在一個從沒跑過 Episode 的 session 上按 —— 也就是它測的是「之前」不是「之間」，一個永遠不清
`_running` 的實作照樣會過。和 §15.25 那條 race 測試是同一個形狀，這是第三次了。

---

## 16. M8 的定案（grill，2026-09-06）

M7 收尾之後的 `/grill-with-docs`。壓的是一個看似只有一句話的問題 ——「接下來是不是繼續做
M8？」—— 結果是 **M8 整個換掉**。

### 16.1 M8 不再是「部署」

§7 原本寫「M8 部署：Docker multi-stage + CI workflows」。那是 M0 訂的，當時這個專案的目標是
「把課堂專案整理乾淨」。

**推翻它的是一個事實：這個專案沒有硬體，而且不會有。** 部署到哪裡？這個 repo 沒有 server、
沒有 web 服務、沒有長駐程序 —— 它是一個要跑在機器人旁邊那台電腦上的程式。沒有機器人，Docker
容器裡跑的就是一個永遠收不到真實影像的 agent。**那是為一個不存在的目標做工程。**

CI 同理：它能 gate 的就是那一千條離線測試，而那些測試在本機跑一次 25 秒。把它搬進 GitHub
Actions 不會讓任何一條斷言變強。

**M8 改成「可執行性與 demo」**：`main()`、系統提示、Journal 落地、本機 demo 介面。
spec 在 `.scratch/m8-runnable-and-demo/spec.md`。

### 16.2 §12.2 那個「翻轉點」的量測不做

§12.2 說感知管線沒有背壓，consumer 只要比 producer 慢就會無限積壓，而它現在沒出事純粹因為
這台機器夠快 —— 原本打算靠 M8 的 x86 容器去證實。

沒有容器了，而那句話仍然可以量（量出 consumer/producer 的成本比、指出翻轉點在哪，不需要真的
跨過去）。**但決定不做**：它是這個專案少數「有數字的真缺陷」，可是它不會變成研究成果，不該
卡在前面。§12.2 的敘述維持原樣，它本來就已經是正確的說法。

### 16.3 M7 留下三個「造好卻沒接線」的東西

這是 M8 存在的實質理由，而不是「順便加個介面」：

| 東西 | 狀態 |
|---|---|
| 系統提示 | **不存在**。`HANDOFF` 訂的條件是「prompt 與 memory 搬出後才刪」舊腳本 —— memory 在 #09 搬了，**prompt 沒有**，而檔案在 #12 刪了 |
| `JsonlFile` | 造好、測過、**零個生產呼叫端**。Journal 是 M7 一路稱為交付物的東西，卻從來沒被寫到磁碟過 |
| `load_api_key` | #12 特地搬進來以免 README 說謊，然後**沒有接線** —— 所以 README 與 `.env.example` 承諾的 `OAI_CONFIG_LIST.json` 那條路實際上不通 |

**三個都接上了**：系統提示 #03（§16.10–§16.12），`load_api_key` #04，`JsonlFile` #06
（§16.22）。

這三個加上 `EmergencyStop` 與 `ToolContext.ears`（#12 才接上）是同一個形狀，已經在 §15.34
記過一次：**一個造好、測到 mutation 全紅、卻沒有呼叫端的東西，會通過專案裡其他每一條測試。**

### 16.4 Demo 的形狀：零相依、本機、頁面重播

- **零新相依。** 標準庫的 `http.server` 綁 localhost，`webbrowser` 自動開啟，手寫 HTML/CSS/JS。
  曾考慮 gradio + HF Spaces（公開網址對申請材料有價值），**否決**：它會拉進二十幾個套件，而
  `requirements.txt` 是一份有論述的文件 —— 每個被移除的套件都寫了理由。為一個 demo 頁面往回加
  相依會讓那份論述變弱。
- **頁面重播完整的 Journal，不做串流。** 視覺結果相同（Episode 本來只有幾秒），但它讓**內建
  範例與真實執行走完全相同的路徑**，省掉一整組串流機制與它的 seam。
- **Python 產畫面資料，JS 只負責畫。** 這條的理由是付過學費的：`TerminalRenderer` 對 `speak`
  印出 `-> , 52cm away`（逗號前是空的，因為只有 `approach` 的結果帶 `result` 鍵）。那個 bug
  不是沒被測到，是**測試蓋不到那一層**。把「顯示什麼」放進 Python，它就落在 pytest 範圍內。
- **內建範例用 `tests/goldens/`**（寫這一節時是四份，M7 #13 之後是五份 —— #08 五份都放，
  第五份標明它是後來加的，見 §16.31），並在畫面上標明它們是**規格、寫在實作之前**。
  刻意不用「我寫一段劇本冒充跑過的紀錄」—— 那是 §15.17、§15.21 那類問題的同一個形狀，而且
  會放在最顯眼的地方。

### 16.5 Journal 預設不落地

Journal 裡有人講的話（`tool_called` 帶 `speak` 的文字、Snapshot 帶 `new_speech`）。預設把對話
寫進磁碟是一個應該由使用者主動開啟的行為。

**而且這個專案至今沒有任何一節談過資料保存** —— 悄悄開啟會是第一個沒有紀錄的決定。

### 16.6 交給 M9 的 README 清單

M9 是「README 與架構圖重寫」。它比表面上大得多：**README 目前大部分在描述 M1 就被移除的系統。**
盤點如下。**用可 grep 的片語定位，不用行號** —— 我第一版寫了行號，然後在同一張票裡刪掉一行，
表格當場就過期了；M9 執行時會再偏更多。

| 章節 | 可 grep 的錨點 | 現況描述了什麼 | 事實 |
|---|---|---|---|
| 開頭一段 | `falling back to [AutoMisty]` | AutoMisty 是 complex task 的 fallback | **M1 就整個移除了**（§2–§3） |
| Demo | `"complex_task": null` | planner 輸出的 JSON 形狀 | M7 改成 function calling，那個形狀不存在了 |
| Highlights | `approach / stay / back_up` | planner 的高階意圖；`approach_user()` | `back_up` 在 §15.2 被砍；後端是 public `approach()` |
| Highlights | `extracted each turn` | 三層記憶，事實每輪抽取 | §15.26：改成 Episode 邊界做一次，而且折疊不刪除 |
| Highlights | `route to the AutoMisty *slow path*` | fast path / slow path 雙軌 | 沒有 slow path 了 |
| Architecture | `The system is a finite-state loop` | `IDLE -> PERCEIVE -> THINK -> ACT` | M7 是 ReAct 迴圈，不是 FSM |
| Architecture | `strict JSON (` | planner 輸出被 whitelist 消毒 | function calling，結構由模型端保證 |
| Architecture | ` ```mermaid ` | 架構圖 | 畫的是上面那整套 |
| Roadmap | `Skill caching` | 重用 AutoMisty 產生的腳本 | AutoMisty 不在了 |

**其中一行在本票中直接刪除**（`exist both at the root`，說 `CUBS_Misty.py` /
`RobotCommands.py` 同時存在於根目錄與 `code/mistyPy/`），其餘留給 M9。

理由是那一行與正上方那句（M7 #12 寫的「這些檔案在 M1 移出版控」）**直接互相矛盾**，而那個
矛盾是 #12 改 README 時自己造成的 —— 留著不是「等 M9 重寫」，是留一句自己打自己的話。其餘
每一項都是 M1–M7 累積下來的、需要重寫整段才能修的，那才是 M9 的工作。

### 16.7 「一筆紀錄怎麼讀」抽出來了，但它比票面宣稱的小（M8 #02）

`describe(record) -> Described(headline, detail, tone)` 是內容，`describe_line()` 只加標點與
縮排。`TONES`（`boundary` / `action` / `result` / `refused` / `failed`）是一個封閉集合，
像 `OUTCOMES` 一樣在建構時驗證。

**票面的第一條驗收「不含任何排版」我沒有做到，而且不打算做到。** Spec 軸的盤點是對的：
`speak(text='hi')` 的括號與引號、`812+11 tokens` 的加號、`2 turn(s)` 的複數形，每一個都是
顯示選擇。要真的做到，`Described` 得改成攜帶結構化的欄位對映 —— 而那會有兩個後果：

1. 終端機會變成 field dump，而 `test_the_terminal_renderer_is_not_a_field_dump` 存在的理由
   正是「兩個訂閱者回答不同的問題」。
2. 那份欄位對映**今天沒有任何呼叫端** —— 它是為 ticket 07 準備的，而這正是 §15.23 刪掉
   `instructions=` 的那個形狀。

所以定案：**`Described` 是一個句子，不是一份資料。** 頁面要欄位就直接讀紀錄（紀錄上就有），
要人話就讀 `describe()`。ticket 07 若需要欄位對映，那時它會有呼叫端與測試。

**代價要說清楚：兩軸都指出這個 prefactor 因此比票面小。** 它買到的是那個 bug 的修正、
一份窮舉的保證、和每種紀錄只有一個地方決定它怎麼讀 —— 不是 §16.4 描述的那個完整 seam。
07 仍然要為它需要的結構化欄位自己出力。

**`tone` 取代了原本的 `depth: int`。** Standards 軸指出 0/1 兩值用 int 是 Primitive
Obsession，而且「invited the surviving `depth=2`」—— 確實有一個 `depth=2` 的 mutation 活著。
換成封閉集合之後，縮排、標記與分隔符全部由 `tone` 推導，而且 `refused` 與 `failed` 分開：
**拒絕是系統在正常運作**（參數超範圍、沒有東西送到機器人），**失敗是系統壞了**。

### 16.8 那個逗號 bug 的第二個入口（M8 #02 review）

修完之後我寫了四條測試蓋「沒有具名結果的 Tool」，全部用 `ok: True`。Standards 軸把
`_came_back` 的 fallback 從 `"returned"` 換成 `""` —— **整套測試照樣綠**，而它渲染出
`  -> , 52cm away`，與這張票要修的 bug 逐字元相同。

原因是我只守了一條路徑。`ok: False`、`{}`、以及只有 `steps` 的結果全都走 fallback，而我一條
都沒測。第二個入口是同一個形狀的另一端：把「detail 為空就不加分隔符」那個分支刪掉，會渲染出
`turn 3, ` —— 也沒有測試會紅。

現在 `_came_back` 的每個分支都有 parametrize 過的測試，而且有一條「不論結果長什麼樣，句子
都有主詞」的全稱斷言。28 個 mutation 全紅。

**教訓與 §15.28 是同一條**：修好一個 bug 之後，要問的不是「我修好了嗎」，是**「同一個洞還有
幾個入口」**。

### 16.9 平行 review agent 不能共用 scratchpad（M8 #02，流程）

Standards 軸回報：它的 worktree 建在 session 的 scratchpad 裡，**跑到一半被平行的 Spec 軸
清掉了**，只好換一個私有路徑重跑。那正是 §14（M6 #06）記過的事，隔了兩個里程碑又發生一次。

往後兩軸的 prompt 要明講 worktree 放在各自的私有路徑，不要放共用的 scratchpad。

### 16.10 系統提示的測試在測「有沒有提到」，不是「說了哪一邊」（M8 #03 review）

兩軸都跑完，Standards 的結論最刺：**16 個 mutation，9 個活著**。接線的部分（persona 有沒有
送出、送在哪個位置）8 個死了 7 個；**內容的部分一個都沒死**，包括把整段提示換成 155 個字的
否定句加 Lorem ipsum —— 全套 1079 條照樣綠。

原因是我把每條內容測試都寫成「某個詞有沒有出現」：

| 改成 | 為什麼還是綠 |
|---|---|
| `Do not take an odd word literally` → `Take an odd word literally` | `"literally" in lowered` 仍為真 |
| `is not yours to choose` → `is entirely yours to choose` | 沒有任何測試讀那個句子 |
| `Stopping is a choice you make` → `is not a choice you make` | `"stopping"` 仍為真 |
| `if you cannot do it with a tool, you cannot do it` → `do it some other way` | `"tool"` 仍為真 |

**一個詞活得過它自己的否定，一個句子不會。** 現在每條內容斷言讀的是**片語**，對著把換行攤平的
`FLAT` 比對。代價是改一句載重的話會弄紅一條測試 —— 那正是要的：這些句子**就是**交付物，改它
應該是一件要簽名的事。上面六個 mutation 現在各被一條測試殺掉。

順帶刪掉 `< 400 字` 那條。它擋不住任何東西（當時 262 字），而且**成本根本沒有被觀測到**：每個
假模型的 `tokens_in` 都是寫死的常數，提示再長也不會有任何斷言看見。一條只會在「有人把散文寫成
兩倍長」時才響的斷言不是行為測試。

### 16.11 提示在解釋一個模型永遠看不到的字串（M8 #03 review）

Spec 軸抓到的：提示裡寫「`"Nobody in view"` 意思是相機找不到臉」。**模型從來沒有讀過那個字串。**
`react.py:_observed` 只送 JSON —— `{"result": ..., "snapshot": {"distance_cm", "face_present",
"new_speech"}}` —— 而且 §15.4 明文否決了「並陳一份人話摘要」。`"nobody in view"` 是
`journal.py` 的 `describe` 產的，走 `TerminalRenderer`，終點是終端機。

**教一個模型去等一個不會到的訊號，比什麼都不說更糟。** 現在提示直接用那三個欄位名解釋，因為那
三個名字**就是**模型的介面。同一類的第二個錯誤：原本寫「每次呼叫工具之後你會被告知看到什麼」，
但被拒絕的呼叫只會 append 一個理由就 `continue`，沒有 Snapshot —— 在模型最需要推理的那個情況
下說錯話。

第三件是**漏掉的**：舊提示的分層規則有兩半，「控制器負責開」搬過來了，「不要講速度、時間、距離」
沒有。而 `episode_invariants` 稽核的是**送進模型的東西**，從來不看模型**吐出來的** `speak` 文字
—— 所以「我往前 20 公分」這句話，不是在提示裡擋，就是沒人擋。補回來了。

### 16.12 `instructions=` 這次真的有呼叫端了（M8 #03 review）

兩軸各自獨立指出同一件事：`run_episode` 的 `instructions=` 參數，**除了它自己的測試以外沒有
任何呼叫端**。`app.py` 的 `Session.episode` 一路用預設值。那正是 §15.23 第一次刪掉它的形狀，
也是 §16.3 那張「造好卻沒接線」清單的形狀 —— 而票面寫的是「**這次兩者都要有**」。更難看的是
`react.py` 那段註解一邊引用 §15.34 的未接線清單，一邊生出一個未接線的參數。

修法是 `Session` 拿一個 `instructions: str = PERSONA` 欄位並明確傳下去。理由不是對稱美觀：
`run_episode` 收的**每一個**接縫（`model`、`memory`、`stop`、`ToolContext`）都是 `app.py`
明確傳的，唯一沒有傳的那個，就是唯一被抓到沒有呼叫端的那個。

`PERSONA` 因此在兩個地方當預設值。這不是 §10 的「同一件事寫兩遍」——兩處都指向同一個常數，
不可能各說各話；`run_episode` 的預設是給測試和直接呼叫端的安全值，`Session` 的欄位是應用程式
的選擇。測試也照 §15.23 的教訓寫了兩條：一條證明 persona 到得了模型，一條**傳一個 fallback
永遠不會產生的值**（`"You are a lamp."`）—— 因為前者在 `Session` 偷偷不傳的時候仍然會綠。

### 16.13 入口：真的感知，假的機器人（M8 #04）

M7 交出一個完整的 agent 和零個啟動它的方法。`Session` 收的是已經建好的協作者，而在這張票
之前，**唯一建過它們的東西是測試**。現在有 `python -m misty_agent`。

**模擬到哪裡為止，是這張票唯一的設計決定。** 機器人是假的、房間是算術：`MovingWorld` 把觀測
距離依照 drive 指令要求的距離移動，那是 `approach` 能收斂的最小世界，也就是「一次 Episode
能被看著發生」的最小世界。但**感知不是模擬的** —— `--image` 走的是 M4/M5 量測時用的同一套
MediaPipe face mesh 和同一個距離估計，出來的數字就是人站的起點。跑一張測試照片是 52cm，
不是任何寫死的值。

**一張沒有臉的照片，得到的是一個沒有人的房間**（`NOBODY_THERE`），不是一個預設距離。給預設
距離等於入口自己發明一個相機沒看到的人 —— 而 `face_present=False` 本來就是 `LivePerception`
會產生的合法 Snapshot，模型該讀到實話。

**「同一個時鐘」這條驗收條件是可以被行為抓到的**，這點事先不明顯。`MovingWorld` 會用它拿到的
時鐘替讀數蓋時戳；如果它拿的是第二個時鐘，那些讀數永遠落在 `approach` 對 Session 時鐘檢查的
新鮮度窗口外，於是 drive 從來不會開始，`approach` 會一路回報「人不見了」而不是「到了」。
不是靠斷言物件圖，是靠斷言模型讀回來的那個 Observation —— mutation 驗證過會紅。

`main(argv, *, model=None, clock=None)` 有兩個可注入的協作者，兩個都有理由：`model=` 因為
只有 live suite 可以花錢（AGENTS.md），`clock=` 因為 `approach` 每一次 drive 都真的會睡，
而且那是判斷世界與 Session 有沒有共用時鐘的唯一辦法。其餘一切都透過**模型被交到手上的東西**
斷言，和 `tests/test_react.py` 同一個接縫：入口組錯世界，現象是一個錯的 Observation，不是
一個錯的物件圖。

**README 沒有動。** §16.6 盤點過它現在大部分在描述 M1 就被移除的系統，整份留給 M9 重寫；
在一份整體錯誤的文件上加一行正確的話，只會讓它更難讀。

### 16.14 兩軸 review：印出來的那一行從來沒有被測過（M8 #04）

Spec 軸把整行 `print(f"perception: {_describe(seen)}")` 換成寫死的字串
`"perception: someone 150cm away"`，**1100 條全綠**。我親手重跑確認過。

原因是唯一斷言那行的測試走的是沒有圖片的路徑，而那條路徑的距離**就是 `DEFAULT_START_CM`
＝ 150**。斷言 `"150" in printed.out` 等於拿一個常數去比對它自己產生的數字 —— 和 §15.29
「拿兩個推導值互比會蓋掉同時影響兩者的錯誤」是同一個形狀。

修法是讓斷言對上**這個模組拿不出來的數字**：跑真的 pipeline 去問那張照片是幾公分，再斷言印
出來的就是那個數。測試不寫 `52`，寫 `what_the_camera_makes_of(portrait)` —— 那個數字是
MediaPipe 的，不該被釘在測試裡。

同一條 finding 的第二半：沒有圖片時把 `DEFAULT_START_CM` 標成 `perception:`，本身就是
§16.13 拒絕過的那件事（「入口自己發明一個相機沒看到的人」）換一張臉。現在那行會講數字從哪來
——`simulated: 150cm away` 對 `photo.jpg: 52cm away`。

### 16.15 同一件事印了兩遍，就印在彼此下面（M8 #04 review）

Standards 軸指出結尾那兩行是同一句話：

```
   6.24s  episode done after 3 turn(s), 3 step(s)     ← TerminalRenderer
done after 3 turns and 3 steps                        ← main() 自己再印一次
```

`_count` 這個函式存在的唯一理由，是把一個**已經被渲染過**的事實重新處理單複數。這是 §15.4
最字面的違反，而且兩份拷貝**已經漂了** —— 一邊 `turn(s)`，一邊 `turns`。整段刪掉，順帶
帶走三個活著的 mutation（`_count` 恆複數、整行刪掉、`turns`/`steps` 對調）：**不能被刪掉
還沒人發現的輸出，本來就不該存在。**

同一軸抓到 `_describe` 是 `journal._in_view` 的第二份拷貝，而且我寫的註解說錯了為什麼要有
第二份（我寫「`_in_view` 讀的是 Record」——它讀的是 Snapshot）。兩份也已經漂了：`_in_view`
處理「有人但距離未知」，我的版本會印出 `someone Nonecm away`。`in_view` 改成公開，`_describe`
刪掉。

`_describe` 裡那段「聽到什麼」的分支則是**永遠到不了的程式碼**：入口的 `Session` 沒有耳朵
（`ears` 預設 `HEARS_NOTHING`，`_microphone()` 回 `None`），所以 `new_speech` 恆為 `None`。
一併刪掉。

### 16.16 `EmptyRoom` 放錯地方，而且它的 docstring 在吹牛（M8 #04 review）

`NEVER_STOPS`、`NO_MEMORY`、`HEARS_NOTHING` 三個 null object **都住在它們所抵銷的那個
protocol 旁邊**。我把 `EmptyRoom` 放進 `misty_agent/fakes/simulated_world.py` —— 但它身上
沒有任何東西是模擬的：它是這個 seam 對「沒有讀數」的合法回答。搬到 `perception/distance.py`，
`DistancePipeline` 旁邊。

docstring 原本寫「省下呼叫端在**每個**建構點都要寫的分支」。呼叫端只有一個，而且它照樣要分支。
改掉了。**一個為了聽起來有道理而寫的理由，比沒有理由更糟。**

### 16.17 一個誠實的等價 mutation（M8 #04）

Standards 列的八個存活 mutation，六個修掉、一個靠刪程式碼消滅，剩下這個沒有：把
`seen = session.sees()` 換成 `LivePerception(session.readings, None).snapshot()`。

它活著是因為**在這條路徑上它真的等價** —— 入口的 Session 沒有麥克風，兩種寫法產生逐欄位相同
的 Snapshot。`sees()` 要保護的不是行為，是「`LivePerception` 只在一個地方被組出來」，而那不是
一條測試能斷言的東西。記在這裡而不是假裝殺掉它。

真正有東西的是它的鄰居：把 `Session._perception()` 的麥克風換成 `None` **也**全綠，而那個
會讓**每一次** Episode 都聾掉。原因是所有耳朵測試都自己手動組 `LivePerception`，沒有一條
穿過 `Session`。補了一條，mutation 現在會紅。這正是 §15.34 的形狀。

### 16.18 真驅動路徑：組起來了，而且永遠不會有人執行它（M8 #05）

`RobotCommands` → `AvSession` → `RtspVideoStream` → `DistancePipeline`，加上共用同一個
`AvSession` 的 `AudioStream`，加上 `EventStream`。`--robot <IP>` 走這條，**預設仍然是模擬**。

**這張票的重點不是「讓它能跑」——沒有人能跑它。重點是讓「線有沒有接上」變成可以被測試的事。**
§15.34 那份清單就是這個形狀：`EmergencyStop` 與 `ToolContext.ears` 造好、mutation 全紅、
完全沒接線，一路到 #12 才被發現。一個忘記接線的 session 會通過這個專案裡其他每一條測試，
同時讓機器人停不下來、而且會聽見自己的聲音再回答它。

所以測試把七個 driver 類別全部換成 recorder，斷言「誰被建出來、拿到什麼、以什麼順序啟動與
停止」。十個 mutation 全紅，包括把 `events=` 或 `ears=` 從 `Session` 拿掉這兩個 §15.34
原版的錯誤。**這不是因為沒有硬體才退而求其次**——就算桌上有一台 Misty II，「保險桿有沒有接到
緊急停止」仍然是接線問題，而接線是在邊界上回答的。

#### 一個不明顯的關停順序

`RtspVideoStream.stop()` 會關掉 `AvSession`，而 `AudioStream` 正在讀同一個 session。先停
影像，聲音那兩條執行緒就會對著一個已經關掉的串流繼續讀。

程式碼做的**就是**啟動的反序 —— 之所以正確，是因為影像最先啟動，反序就把它排到最後。這裡值得
記的是「為什麼反序剛好對」，不是「反序不夠」。`started` 是邊啟動邊追加的（先 `start()` 再
`append`），所以啟動失敗到一半時，只會停掉真的起來的那些。

#### 時鐘只傳得到它傳得到的地方

`Session` 和 `AudioStream` 拿得到注入的時鐘。`RtspVideoStream` 和 `DistancePipeline`
**拿不到**——它們自己呼叫 `time.monotonic()` 蓋時戳，而且沒有參數可以換掉。

這件事有後果：`approach` 是拿讀數的 `frame_arrived_at` 去和 **Session 的**時鐘比對新鮮度。
在這條路上兩者一致，因為 `SystemClock.monotonic` 就是 `time.monotonic` ——同一個函式，不是
兩個剛好相等的東西。**在這裡放一個假時鐘會直接弄壞新鮮度判斷**，和 §16.13 記的那個「世界拿到
第二個時鐘」是同一個故障。

為了讓 docstring 能寫「全部共用一個時鐘」而去替那兩個類別加時鐘參數，會做出一個「只有一個
呼叫端、只傳一個值」的參數——正是 §15.23 刪掉過的形狀。所以是記在這裡，不是加參數。

#### 沒有 key 就沒有耳朵

`AudioStream` 要一個 `Transcriber`，而 hosted 那個要 key。沒有 key 時這條路拿 `HEARS_NOTHING`
而不是拒絕連線——**一台沒有耳朵的機器人仍然值得連上去**，它的相機會回答，而那件事本身就告訴
你連線是通的。

### 16.19 沒有 key 的那條路整段沒有測試（M8 #05 review）

兩軸各自跑完，最有用的一條是 Standards 的：**§16.18 那段「沒有 key 就沒有耳朵」完全沒有
測試蓋到**。這個檔案裡每一條測試都設了 `OPENAI_API_KEY`，所以 `ears` 從來不是
`HEARS_NOTHING`，兩個 mutation 因此活著 —— 刪掉那個守衛、以及不管有沒有 key 都建 transcriber。

而 `HearsNothing` 只有 `mute_for`，沒有 `start` 也沒有 `read`。也就是說**真的沒有 key 去跑
`--robot`，會丟 `AttributeError`** —— 在一台沒有人能測的機器上。散文寫了一件事，程式碼靠一個
沒有測試的守衛撐著它。補了一條沒有 key 的 `--robot` 測試，兩個 mutation 一起死。

順帶把那個守衛拿掉了。`HearsNothing` 的 docstring 說它存在是為了「讓呼叫端讀一種形狀，不用寫
`None` 檢查」，而 `attached_to` 一邊收 `Optional[transcriber]` 一邊又比對 sentinel，**把它省
下來的那個檢查加了回去，還加了兩次**。現在耳朵和「要啟動什麼」在同一個分支裡一次決定完。

### 16.20 一個叫做 `model` 的布林值（M8 #05 review）

`_one_episode(session, args, *, source, model)` 裡的 `model` **不是模型** —— `session.model`
才是。它唯一的用途是 `if model is None and not api_key_available()`，也就是「有沒有人注入了
測試替身」。一個穿著協作者名字的布林值。改名 `must_find_a_key`，呼叫端算 `model is None`。

同一輪還修掉：`--robot ""` 是 falsy，所以會安靜地跑模擬（而按下 `--robot` 唯一確定的事情就是
這個人不要模擬）；parser 的 description 仍然寫著「against a simulated robot… the robot is
not」，在 `--robot` 底下是假的；以及 `load_api_key` 被搬成每次 `main()` 都跑 —— 它會**寫入**
`os.environ`，而一個拿到模型又不連機器人的指令沒有理由在路過時改動環境。

### 16.21 §16.18 的論證少了一顆釘子（M8 #05 review）

Standards 指出：§16.18 說「`RtspVideoStream` 與 `DistancePipeline` 自己讀 `time.monotonic`
沒關係，因為 `SystemClock.monotonic` 就是 `time.monotonic`」—— 而**那個前提本身沒有任何測試**。
整段論證掛在一個沒人檢查的等式上。

釘上了，而且是行為斷言不是原始碼比對：夾在兩次 `time.monotonic()` 之間取一次
`SystemClock().monotonic()`，斷言它落在中間。換成 `time.time()` 立刻紅。

**教訓和 §16.10 是同一條**：一段推理如果有一個「因為 X」，那個 X 就是要被斷言的東西，不是被
複述的東西。

### 16.22 Journal 預設不落地（M8 #06）

`JsonlFile` 從 M7 就造好、測過，**零個生產呼叫端** —— Journal 是 M7 一路稱為交付物的東西，
卻從來沒有被寫到磁碟過。這是 §16.3 那張表上三個「造好卻沒接線」的第二個（系統提示 #03 補了，
`load_api_key` #04 補了），**表清空了**。現在 `--journal PATH` 會寫，**不給就完全不碰磁碟**。

**預設不寫，是一個決定，不是一個省略。** Journal 裡有兩邊講的話：`tool_called` 帶著 `speak`
的文字（**機器人自己說的**），而每一個 Snapshot 帶著 `new_speech`（**人說的**，逐字的語音
轉錄）。第二個才是隱私上要緊的那個，第一版把兩者寫成同一件事了。把對話寫進磁碟應該是使用者主動開啟的行為，而
這份 `PLAN.md` 到今天為止沒有任何一節談過資料保存 —— 悄悄開啟會是這個專案第一個沒有紀錄的
決定。所以它記在這裡，而且有一條陰性對照測試證明預設下 `JsonlFile` 根本不會被建構。

**一個檔案一次 Episode。** 這不是偏好，是格式：`tests/goldens/` 每一個檔案都是一次 Episode，
而 `from_jsonl` 回傳的是一個扁平序列、**不會分組**。往一個已經有內容的檔案後面接第二次
Episode，讀出來會是「一次有兩個開頭的執行」，等於把第一份證據弄成不可讀。所以路徑已經存在時
是**拒絕**，不是覆蓋也不是附加 —— 永遠不要寫在證據上面。

參數放在 `Session.episode()` 而不是 `Session`，理由同上：一個 Session 可以跑很多次 Episode，
而一個路徑只裝得下一次。

**它是 subscriber，不是結尾的 `to_jsonl()`。** 被中斷的 Episode 應該留下它已經走完的部分，
那正是 `JsonlFile` 逐行 append 的理由。

### 16.23 「中途被中斷」這條測試差點測不出東西（M8 #06）

第一版的斷言是「`KeyboardInterrupt` 之後檔案裡有前兩筆」。我拿一個**在 `finally` 裡把整份
`to_jsonl()` 一次寫出去**的版本去跑 —— 綠的。因為 `finally` 對 `BaseException` 一樣會執行，
兩種寫法留下的位元組完全相同。

分辨得出來的觀察只有一個：**檔案在 Episode 還在跑的時候就已經有內容**。所以現在是模型在
`decide` 裡把檔案讀起來，斷言那個當下就有前兩筆。逐行 append 真正買到的東西是「行程被殺掉
（而不是被展開）也還在」，而那件事只有「跑到一半就已經在磁碟上」能證明。

同一輪的第二個：「預設不寫」原本斷言一個 `tmp_path` 底下的空目錄仍然是空的 —— 對一個寫到
別處絕對路徑的 mutant 完全無效，它證明的是一個無關的目錄沒有變。改成斷言 `JsonlFile`
**根本沒有被建構**。

**和 §16.14 是同一條**：斷言要對著主張本身，不要對著一個剛好也成立的鄰居。

### 16.24 寫不進去的路徑：整場跑完、什麼都沒留下、然後回報成功（M8 #06 review）

兩軸各自獨立跑出同一件事，而且都是真的跑出來的：

```
--journal /tmp/nope/out.jsonl
   0.00s    ! JsonlFile failed on episode_started: [Errno 2] No such file...
   ... 每一筆紀錄都印一次 ...
   0.00s  episode done after 2 turn(s), 0 steps
EXIT CODE: 0
```

**機器人動了、證據沒有了、指令說成功。** 原因是 `Journal` 會接住 subscriber 丟出來的例外、
記成 `SubscriberFailed`、然後繼續 —— 那對 renderer 是對的，對證據是錯的。一個要求留存的人
拿到乾淨的 exit code，等於被告知「留下來了」。

修法有兩層，而且兩層都必要：

1. **`JsonlFile` 在建構時就用 `open(path, "x")` 把檔案獨佔建立起來。** 一個呼叫同時買到兩個
   保證：路徑寫不進去的話**現在**就失敗（在任何東西動之前，而不是每筆紀錄失敗一次），以及那
   個路徑不是別人的 Journal。
2. **Episode 結束後檢查 `journal.subscriber_failures`**，有 `JsonlFile` 就回非零並說明。這條
   蓋的是事前檢查不到的：跑到一半磁碟滿了、目錄被刪掉。

**「一個檔案一次 Episode」原本只寫在 CLI 裡，那是錯的層。** Standards 的說法一針見血：訊息屬於
`main`，**保證不屬於**。`Session.episode(journal_path=...)` 是這張票新增的接縫，一個直接用它
的呼叫端照樣會往別人的檔案後面接。現在保證跟著格式走，`main` 只負責把兩個人真的會犯的錯講成
一句話而不是一個 traceback。

### 16.25 我的陰性對照自己把自己的前提蓋掉了（M8 #06 review）

Standards 抓到的，而且它就在 §16.23 的下一個 commit：

```python
kept.write_text("")
kept.write_text('{"type": "episode_started"}\n')
```

第一行被第二行覆蓋掉了。**「空檔案已經存在」這個情況從來沒有被跑過**，所以把檢查從
`exists()` 改成「存在**而且**有內容」可以通過全部 1133 條。空檔案不是沒有意義的情況：它是
別人剛開始的一次執行，或是有人故意放的 —— 兩種都不是我們可以寫進去的。改成 parametrize，
兩個都跑。

第二個：**§16.22 整段的理由是「Journal 裡有人講的話」，而沒有任何一條測試讀過裡面的一個字。**
round-trip 測試對一份把每個字都清空的檔案照樣會綠 —— 空字串一樣 round-trip。補了一條直接
斷言 `speak` 的文字在檔案裡。

**同一條教訓第三次**（§16.10、§16.14、這裡）：一段推理裡的「因為 X」，X 就是要被斷言的東西。

### 16.26 `said` 不在 Journal 裡

Spec 軸順手發現的，記著但這張票不動：**觸發這次 Episode 的那句話沒有被寫進 Journal。**
`EpisodeStarted` 只帶 `trigger`，`said` 只流向模型的 working context 與 Memory。

不動的理由是它會改 schema：`EpisodeStarted` 加一個欄位，五份 golden 的第一行全部要改，而
`tests/goldens/README.md` 的規矩是「哪一邊讓步是一個決定，要寫進 `PLAN.md`」。那是一張自己
的票，不是 #06 順手做掉的事。

順帶澄清 `journal_diff.py`：它讀得了產出的檔案（跑過了），但拿一次真的執行去跟 golden 比一定
在第 0 筆就停 —— `episode_id` 來自 `int(time.time())`、`started_at_wall_clock` 來自
`datetime.now()`。那是設計，不是缺陷：goldens 是用釘死的 id 與 wall clock 產生的，而
`EpisodeStarted` 帶著整份 Journal 唯一的絕對時間本來就是為了讓其他每一筆都可以逐位元組比對。

### 16.27 畫面上顯示什麼，是在 Python 裡決定的（M8 #07）

`storyboard_of(records)` —— 紀錄進，一個可以 `json.dumps` 的結構出，JavaScript 只負責畫。

**這是整個 M8 的測試策略，不是一個實作偏好。** 相反的做法（伺服器丟原始 JSONL、瀏覽器自己
解讀每一行）會把「畫面顯示什麼」整個搬到這個 repo 裡沒有任何測試看得到的地方。而這件事這個
專案已經付過一次代價了：`TerminalRenderer` 對除了 `approach` 以外的每個 Tool 都印出
`-> , 52cm away`，連續四個 commit 沒有任何東西變紅 —— 因為測試斷言的是 Journal，而缺陷在
**被顯示出來的東西**（§16.7）。

**它是那句話，加上那句話刻意不帶的東西。** 一筆紀錄怎麼讀是 `describe` 的答案（#02 定的），
這裡沿用而不是再寫一份（§15.4）。`Described` 當時**拒絕**了一個 `facts` mapping，理由是
「今天沒有任何呼叫端」—— 現在有了。

`Moment.facts` 是從紀錄身上機械地取下來的：`asdict(record)` 扣掉 `Moment` 自己已經有的四個
欄位。所以票面三條關於**內容**的驗收條件（拒絕的理由、模型呼叫的成本、四種結束方式）不需要
任何專屬程式碼 —— 它們是欄位，而欄位全都會到。一個紀錄種類將來多一個欄位，這裡也會自動多。

#### 機器人狀態是折疊出來的，而且有兩條規則來自 `tools.py` 的實際行為

`Moment.robot` 是那筆紀錄之後**整個**機器人，不是變化量：畫第七筆的頁面不該需要先重播前六筆。

1. **參數只有被記錄下來才算數。** `dispatch` 先驗證、通過了才記 `ToolCalled`，所以被拒絕的
   呼叫從來不會產生一筆。從 `ToolRejected` 讀姿勢會畫出一顆轉到系統剛剛拒絕的角度的頭。
2. **掃描會回報它停在哪裡。** `look_around` 不會掃回正中間 —— 它停在找到的人身上，好讓之後那
   個 Snapshot 講的是那個人 —— 而它把角度寫在**結果**裡，不是參數裡。所以折疊也讀結果。

`MOVES` 用字串指名 Tool，這條耦合沒有任何 type checker 跨得過去。測試補上：每個名字都必須
還在 registry 裡，否則一個改名會讓頁面畫出一台永遠不動的機器人，而且悄無聲息。

#### 兩個新詞

`CONTEXT.md` 加了 **Storyboard** 與 **Moment**，放在新的「畫面」一節。`Trace` 不能用 ——
它是 harness 的量測產物，而 `Journal` 的 _Avoid_ 明文寫著不要叫它 trace。`Frame` 也不能用，
`av_stream.py` 的 `CapturedFrame` 是相機影格。模組叫 `storyboard.py` 而不是 `view.py`：
第一版兩者都做了 —— 在同一個 commit 裡把 `view` 寫進 _Avoid_，然後拿它當檔名（§16.28）。

#### 呼叫端在下一張票

`storyboard_of` 今天只有測試在呼叫，#08 的 demo 伺服器是生產呼叫端。這**不是** §15.23 的形狀：
那條講的是零呼叫端**且零測試**的參數，而這是一張票的交付物本身，有 23 條測試，而且下一張票
被它擋著。記在這裡，是因為這個里程碑已經因為「造好卻沒接線」被抓過兩次，值得先講清楚差別。

### 16.28 頁面畫出一盞從來沒亮過的燈（M8 #07 review）

兩軸都抓到同一件事，而它正是這張票開頭引用的那個形狀。

`dispatch` 先記 `ToolCalled`，**然後**才呼叫 handler。handler 丟例外的話，`react.py` 記一筆
`ExecutionFailed`，**沒有 Observation**。而我的折疊只在 `ToolCalled` 上讀姿勢，所以：

```
tool_called      led=(255, 0, 0)
execution_failed led=(255, 0, 0)     ← 燈根本沒亮
episode_finished led=(255, 0, 0)
```

我寫在 `view.py` docstring 裡的規則是「參數只有被記錄下來才算數」，那句話只推理了**被拒絕**的
情況；handler 炸掉落在那條規則的另一邊，而我沒想到。

改成兩筆紀錄的事：`ToolCalled` 讓姿勢變成**待確認**，`Observation` 才把它兌現，其他任何東西
都把承諾丟掉。順帶把 `ToolCalled` 那一刻畫成「還沒發生」，那也比較誠實 —— 模型開口要紅色的
當下，燈確實還不是紅的。

### 16.29 23 個 mutation 活了 15 個（M8 #07 review）

Standards 的數字。我自己只跑了七個，而且都集中在折疊邏輯上；**沒有被我碰到的地方，一個都沒有
被測到**：

| 活著的 | 意思 |
|---|---|
| `trigger` / `started_at` / `turns` / `steps` 全部寫死成 null | `Storyboard` 七個欄位裡有四個沒有任何斷言，而那四個是頁面最先讀的 |
| `arms` 預設改成 `(0,0)`、`expression` 改成 `"happy"` | `assert robot == RobotState()` 是**同義反覆** —— 拿預設值去比預設值 |
| `detail` 全部清空 | 每一個 Snapshot 片語、每一個拒絕理由、每一個 token 數從頁面消失，1163 條全綠 |
| `_ALREADY_ON_THE_MOMENT` 多加一個名字 | §16.27 說「紀錄多一個欄位這裡也會自動多」—— 那句話沒有任何測試 |

**Standards 對第三個問題的回答值得抄下來**：§16.27 拿「23 條測試」當作「這不是造好卻沒接線」
的論據，而那個論據的承重點正好是 15 個 mutation 活過去的地方。有測試不等於測到了。

另外兩個是我自己該看見的：
- `len(given) == len(names)` 那個保護分支**在生產環境永遠為真** —— `dispatch` 記的是
  `model_dump()`，pydantic 會把每個預設值填滿。一個到不了的分支，而且它的 `return robot`
  正好是這個模組 docstring 警告的那種無聲失效。刪掉。
- `_after` 用 `_facts(record).get("result")` 去拿掃描角度，讓**機器人的折疊繞過顯示用的排除
  清單** —— 在 `_ALREADY_ON_THE_MOMENT` 裡多寫一個 `"result"` 會無聲地殺掉掃描。改成直接讀
  `record.result`。

還有一個我沒有補測試而是記下來的：`next(...)` 取第一筆 `EpisodeStarted` 改成取最後一筆，在
任何合法的 Journal 上都是等價的（一次 Episode 只有一個開頭）。要測它得先偽造一份不可能存在的
Journal，那測的是別的東西。

### 16.30 同一個 payload 裡把五個值送了兩遍（M8 #07 review）

`trigger`、`started_at_wall_clock`、`outcome`、`turns`、`steps` 被提升到 `Storyboard` 上，
**同時還留在對應那筆 Moment 的 `facts` 裡**。§15.4 的字面違反，而且我自己在 `_facts` 上面的
註解就寫著「同一個值不要在一個物件上出現兩次」—— 我只想到了 `Moment`，沒想到 `Storyboard`。

規則改成一句話：**一份 payload，每個值只有一個家。**

### 16.31 Demo：純函式回答，socket 是薄殼（M8 #08）

`answer(method, path)` 是 HTTP 的一切，除了 socket：請求進，狀態、標頭、位元組出。`serve()`
綁 loopback、開瀏覽器、把每個請求交給 `answer`，而且**不測** —— 和 `main()` 同性質，裡面沒有
測得到的東西可以出錯。`--demo` 掛在既有的指令上（spec.md 的入口那一節就是這樣寫的）。

**零新相依，這是論述不是偏好。** `http.server`、`webbrowser`、手寫 HTML。測試不是相信意圖，
而是**用 AST 讀這個模組的 import**，扣掉 `sys.stdlib_module_names` 和 `misty_agent` 之後必須
是空集合。

**只綁 127.0.0.1。** 一個聽所有介面的 demo，會把一份 Journal —— 裡面有人講的話 —— 放到筆電
剛好連著的那個網路上。

#### 範例是讀 `tests/goldens/`，不是拷貝

一份拷貝可能和它宣稱代表的規格不一樣，而那正好發生在**唯一一個要求訪客認真看待這個宣稱的
地方**。`harness/__main__.py` 早就為了同樣的理由伸手進 `tests/fixtures/` 拿它重播的那張照片：
被討論的那個東西，就是 repo 裡的那一個。

#### 五份，不是四份 —— 而第五份不會宣稱自己是規格

票面和 §16.4 都寫「四份」，但 `tests/goldens/` 現在有五個檔案。`tests/goldens/README.md` 講得
很清楚：原本四份寫在 ReAct 迴圈存在**之前**，第五份是 M7 #13 為了釘住 `error` 這條收尾路徑
才加的 —— **寫在實作之後**。

把五份都標成「規格，寫在實作之前」，會是在這個專案最顯眼的地方講一句假話，而那正是這張票存在
的理由。所以來歷是**逐個範例**的，而且跟著 payload 走而不是只寫在 HTML 裡 —— 一句由 JavaScript
印出來的宣稱是一句這裡沒有測試讀得到的宣稱，那正是 `storyboard.py` 存在要補的洞。頁面上
`episode_fails_during_model_call` 會拿到不同顏色的橫幅，寫著「這一份是後來才加的」——用檔名
而不是序號，因為序號會隨著清單排序過期。

`test_every_golden_on_disk_has_been_given_a_provenance` 擋住第六份 golden 悄悄繼承別人的宣稱。

#### 一個誠實的侷限

**五份 golden 裡沒有任何一份成功呼叫過 `change_led`、`move_arms` 或 `display_image`。** 它們
呼叫的是 `speak`、`approach`、`look_around`、`done`，加上一次被拒絕的 `move_head`。所以旁邊
那個機器人狀態圖上，燈永遠是暗的、手臂永遠在原位、表情永遠是 neutral；會動的只有頭 ——
`episode_hits_the_turn_limit` 掃描八次，每次都在 -60° 找到人，那個轉頭是真的看得見的。

**不去改 golden 來讓 demo 好看。** `tests/goldens/README.md` 的規矩是「哪一邊讓步是一個決定」，
而為了展示效果去動一份寫在實作之前的規格，會毀掉它唯一的價值。狀態圖要活起來，靠的是 #10
餵真實輸入之後跑出來的 Episode。記在這裡，免得下一個看到那張圖的人以為它壞了。

### 16.32 我在「要保持誠實」的那個橫幅上寫了一句假話（M8 #08 review）

Spec 軸抓到的，而且這是這一輪最該記的一條。

第一版的橫幅寫著：**「the loop had to be built to produce it, not the other way round.」**
`tests/goldens/README.md` 自己就有一張表，記著每一次 golden 與實作對不起來時哪一邊讓步：

| 次數 | 讓步的是 |
|---|---|
| 5 | 實作 1 次，**golden 4 次** |

`episode_hits_the_turn_limit` 之所以跑八個 turn，正是因為**那份 golden 被改成配合程式**
（§15.19，turn cap 從 5 升到 8）。而它身上掛著那句紫色的「不是反過來」。

**這是這張票存在要防的那個錯誤，而我在寫防它的程式時犯了它。**

修法不是把話講小，是把話講對 —— 而講對的版本是更好的故事：一條從來沒有被援引過的規矩不是
規矩，這一條的價值在於**每一次援引都有人寫下哪一邊動了**。所以橫幅現在有兩段，第二段是
`AMENDMENTS`，而且它跟 `written_before_the_implementation` 放在**同一個物件裡**送出去，
好讓「保留吹噓、丟掉但書」變成一件做不到的事。測試從 README 的表格數行數，第六次援引會讓
頁面上的數字變紅而不是變舊。

### 16.33 那句話會在按下 Play 的瞬間離開畫面（M8 #08 review）

同一軸的第二個：`scrollIntoView` 捲的是**視窗**，所以量到的是 `scrollY` 787、橫幅在 -551 ——
「不得讓觀看者誤認」的那句話，在任何人開始使用這個頁面的第一秒就不見了，而右邊那個 sticky
的機器人圖還好端端釘在那裡。紀錄列表現在有自己的捲動框，捲的是列表不是視窗。

窄螢幕（375px）也修了：原本機器人圖排在時間軸**下面**，量到的是列表底 1385px、圖頂 1411px
—— 整場都在畫面外，所謂「跟著時間軸走」跟著了個空。現在它排在上面。

### 16.34 三個永遠不動的讀數看起來像壞掉（M8 #08 review）

§16.31 老實記了「沒有 golden 會點燈或動手臂」，但那句話寫在 `PLAN.md` 裡 —— **訪客看到的是
三個永遠停在預設值的讀數，和沒有任何說明**。

`what_moves(storyboard)` 算出這一次 Episode 到底有哪些部位變過，跟著 payload 一起送。掃描
那份會說「moves here: head」，第一個 turn 就結束那份會說「nothing on this figure moves in
this episode」。算在 Python 裡，理由和其他每一個顯示決定一樣（§16.4）。

### 16.35 #08 做掉了 #09 的一半（M8 #08 review）

Spec 軸點名：Play/暫停、拖曳軸、鍵盤、機器人 SVG、語氣顏色 —— 那是 #09 八格裡的六格。

理由是 spec 的版面要求本身就寫著「機器人狀態圖**跟著時間軸走**」，而「跟著走」需要一個時間
軸位置，也就需要某種控制。但範圍確實溢出了，記在這裡免得 #09 打開來發現自己只剩兩件事。

**#09 還沒做的**：點一筆紀錄展開看原始欄位（「可追溯」不只是一句話）。

（原本這裡還寫了「以及 token 與延遲的總計」—— **那是我加的，票面沒有這一格**。#09 第七格是
「每次模型呼叫的耗時與 token 數看得到」，per-call，`describe` 已經在做。改掉，免得下一個人
去做一件沒有人要求的事。同一段還寫了「資料已經在 `Moment.facts` 裡了」，那句也不準 ——
見 §16.37。）

### 16.36 兩個 review 提醒的小事（M8 #08）

- **`timeline` 在 `CONTEXT.md` 的 _Avoid_ 清單上**，而我拿它當 DOM 的 id 和 class。和 #07
  把 `view` 寫進 _Avoid_ 然後拿它當檔名，是同一個錯誤，隔一張票又犯一次。改成 `moments`。
- **`tellingFacts()` 在 JavaScript 裡組句子** —— `face ${...? "in view" : "not found"}` ——
  正是 §16.4 存在要防的那層。而且它對 `tool_called` 印的參數，`describe` 的 headline 已經
  印過一次。整個刪掉：`describe` 說的話就是頁面顯示的話。收尾那行同理，改成讀最後一個
  Moment 的 headline 與 detail。
- **`answer` 不是全函式**：golden 檔案不見時它會 raise 而不是回一個 `Reply`，與它自己
  docstring 承諾的「狀態、標頭、位元組出」矛盾。改成回 500 並說明。
- **`answer` 沒有 `body` 參數**，而票面與 `spec.md` 都寫了。兩軸都同意 §15.23 適用 ——
  今天沒有東西傳它、沒有東西讀它，而且非 GET 在任何 body 有意義之前就被擋掉了。#10 要 POST
  的時候再加。這是一次**明確記下的偏離**，不是漏掉。
- `misty_agent/demo/` 讀 `tests/goldens/`：Standards 指出我把 `harness/` 的先例講得太滿 ——
  `harness/` 是旁邊的量測工具，不是會被安裝的套件。這條路在一份不含 `tests/` 的安裝裡會斷。
  接受這個代價，因為拷貝一份會讓「頁面上這份就是那份規格」變成一句需要被相信的話。

### 16.37 「可追溯」給的是檔案裡那一行，不是重畫一次（M8 #09）

票面第三格是這張票唯一沒被 #08 順手做掉的：**「點任何一筆紀錄可以展開看到原始欄位 ——『可追溯』
不只是一句話」**。

我在 §16.35 寫過「資料已經在 `Moment.facts` 裡了」。**那句不準**，而且不準的地方正好是重點：
`facts` 少了 `t`、`turn`、`type`（它們在 `Moment` 上），而 `episode_started` 與
`episode_finished` 的欄位又被提升到 `Storyboard`（§16.30）—— 展開那兩筆會幾乎是空的。用
`facts` 拼回一筆紀錄，是在頁面裡重畫一份**看起來像**原始資料的東西。

所以多了一條路由 `GET /examples/<名字>/journal`，直接把那份 golden 的位元組送出去。訪客展開
一筆紀錄，看到的是**檔案裡的那一行**：

```json
{ "episode_id": "ep-several-turns", "reason": "pitch 140 is outside the permitted range",
  "t": 1.198, "tool": "move_head", "turn": 1, "type": "tool_rejected" }
```

頁面用**位置**把 Moment 和行配起來，而那件事之所以合法，是因為 `storyboard_of` 對紀錄是一對一
的映射 —— 五份 golden 各自被斷言過行數與 Moment 數相等、`t` 與 `type` 逐項相同。如果哪天不再
一對一，展開會把**另一個決定**的欄位給訪客看，那比什麼都不給更糟。

#### 一個誠實的等價 mutation，和怎麼把它變成不等價

把「送檔案」換成「`to_jsonl(from_jsonl(檔案))` 再送」，40 條測試全綠 —— 因為 golden 本來就是
那個形狀，逐位元組相等。它是這批資料上的**等價 mutation**。

但兩者的主張不同：一個是「這是磁碟上那一行」，另一個是「這是我們重新產生的一行」。分辨的辦法
是拿一個**不是** canonical 形狀的檔案去測（鍵序不同、多一個空格），於是那條測試改用 tmp_path
放一份刻意排版怪異的檔案。現在 mutation 會紅。

#### 順帶

四種結束方式各自有顏色（綠 done、琥珀 turn_limit、藍 aborted、紅 error），因為票面第五格要求
「結束方式在畫面上明顯」，而一行同樣灰的字不算明顯。展開的區塊要 `grid-column: 2` —— `li` 是
兩欄的 grid，不指定的話它會掉進 62px 的時間戳欄位裡，一個字母寬地直著印下來。

### 16.38 那條「比什麼都不給更糟」的路，我自己走上去了（M8 #09 review）

§16.37 我親手寫下：「如果哪天不再一對一，展開會把**另一個決定**的欄位給訪客看，那比什麼都
不給更糟。」然後我把配對放在**沒有任何測試看得到的 JavaScript** 裡。

兩軸各自從不同角度撞到同一件事：

- **Spec 軸實際重現了它。** `load()` 先 await 拿 storyboard、再 await 拿 journal，中間沒有
  任何世代守衛。快速點兩個範例，就會出現「A 的 Moment 配 B 的行」——它按下
  `episode_ends_on_the_first_turn`，展開第 0 筆，看到的是 `"episode_id": "ep-turn-limit"`。
- **Standards 軸用 mutation 證明沒人會發現。** 把 `state.lines[index]` 改成 `[index+1]` ——
  **每一筆都配到下一筆的行**——1216 條全綠。它一併指出：**沒有任何測試讀過 `page.html`**，
  所以那個檔案裡的四個 mutation 全部活著。

**修法不是加測試，是把「配對」這件事消滅掉。** 每一個 Moment 現在自己帶著它被做出來的那一行
（`moment["line"]`），由 `_example` 在 Python 裡 zip 好送出去。頁面沒有 index 可以錯，那條
獨立的 `/journal` 路由整條刪掉——順帶解決了 Standards 問的 Q1（`_journal` 與 `_example` 六行
重複，而且各自寫了一次路徑穿越的防禦）。

長度不一致時是**回 500 而不是硬配**。它不可能發生（`storyboard_of` 對紀錄一對一），拒絕它是
因為它一旦發生，造成的正是這一節開頭那個失敗。

#### `facts` 與 `line` 同時在 payload 裡，這是刻意的

`Moment.facts` 是 #07 的合約（票面要求「拒絕的理由」「模型呼叫的成本」出現在**結構**裡），
`line` 是 #09 的交付物（原始欄位、逐位元組）。兩者不會漂——同一次呼叫、同一筆紀錄——而且
用途不同：一個是「給程式讀的欄位」，一個是「給人核對的證據」。頁面今天只讀後者。

### 16.39 我的「非 canonical」測試只測了兩條軸裡的一條（M8 #09 review）

§16.37 說「拿一個不是 canonical 形狀的檔案去測」就能把「送檔案 vs 重新產生」分開。Standards
指出我的檔案只在**鍵序與空白**上怪，而兩者真正會分岔的另一條軸是**行尾**：

`read_text()` 會做 universal-newline 轉換，`\r\n` 進去 `\n` 出來 —— 也就是說，把
`read_bytes()` 換成 `read_text().encode()`，我那條測試照樣綠，而「這是磁碟上那一行」的主張
已經不成立了。現在的測試檔案用 `write_bytes` 寫入 `\r\n` 與一個非 ASCII 欄位，兩條軸都蓋到。

### 16.40 三個互動缺陷，都在唯一那格新功能上（M8 #09 review）

Spec 軸把頁面當成一個人在用，抓到三個：

1. **選取 JSON 會把它關掉。** click handler 掛在整個 `li` 上，所以想把原始欄位反白複製的人
   一拖曳就把面板關了 —— 在這張票唯一的新功能上。現在忽略來自 `.raw` 內部的點擊，也忽略
   有選取時的點擊。
2. **展開的區塊會卡住。** 展開一筆、再把時間軸拉回它之前：區塊留在一個「還沒發生」的紀錄裡，
   18% 透明度、`aria-expanded="true"`，而且關不掉（`showLine` 對未顯示的列直接 return）。
   現在 `seek` 會把不再顯示的列一併關上。
3. **空白鍵會觸發兩次。** `preventDefault()` 不會阻止冒泡，所以在一筆紀錄上按空白鍵會展開它
   **並且**讓 document 的 handler 開始播放 —— `state.at` 從 15 跳回 0，讀的人失去位置。

順帶：`function open(index)` 在傳統 script 裡會蓋掉 `window.open`。改名 `showLine`。

### 16.41 `turn_limit` 是個 enum，不是一句話（M8 #09 review）

票面第五格是「Episode 的結束方式在畫面上明顯（自己停 / 撞上限 / 被中止 / 出錯）」，而畫面上
印的是 `episode turn_limit after 8 turn(s)` —— 那是 `describe` 給終端機的句子，對終端機是對的，
對一個看申請材料的人是一個沒見過的 enum。而 `aborted` 的色條用的是 `--boundary`，和每一行
headline 同一個灰藍，等於沒有色條。

`storyboard.py` 多了 `ENDINGS` 與 `Storyboard.ending`：同一件事說給不同的讀者聽，不是第二個
關於「發生了什麼」的答案 —— 它來自 `Storyboard` 已經有的那個 `outcome`。四個結束方式現在各自
有一句人話和一個真的分得開的顏色（綠 / 琥珀 / 藍 / 紅）。

### 16.42 頁面可以自己跑一次了（M8 #10）

拖一張照片進去、打一句話，按 Run it。

**感知那一半是免費的，所以它無條件跑。** MediaPipe 在這台機器上跑、不需要 key，所以任何人
上傳一張照片都會拿到「找到臉、幾公分、有沒有在看鏡頭」—— 只有後面的決策要 key。而不能給
key 的人看到的解釋，是 `MissingApiKey` 已經寫好的那一段（§16.24 讓它同時講兩條通道），不是
第二份說明。

**上傳的東西不落地。** 圖片用 `cv2.imdecode` 在記憶體裡解，音檔用 `wave` 在記憶體裡解。這個
專案裡唯一會把一次執行寫到磁碟的東西是 `JsonlFile`，而走到它要 `--journal`（#06）—— 那是一個
關於保存別人的話的決定，做過一次，寫下來了。

#### `answer` 現在有 `body` 了，因為終於有人送

#08 我刻意沒有加這個參數，理由是「沒有東西傳它、沒有東西讀它」——那正是 §15.23 刪掉過的形狀
——而且我把這個偏離明確記下來讓兩軸評斷，兩軸都同意。**現在有 POST 了，參數跟著需求一起出現。**
這就是那條紀律該有的樣子：不是猜將來會用到，是等到用到。

#### `Example` 的布林值長成了第三種狀態

`written_before_the_implementation: bool` 撐不住 #10：一次剛跑完的執行**也不是**寫在實作之前
的，但它和「後來補的那份 golden」完全不是同一件事。用同一個 `False` 表示兩者，等於把票面那句
「不得讓觀看者搞混哪個是規格、哪個是剛跑的」交給頁面自己判斷。

改成 `kind`，三個值：`specification` / `added-later` / `live`。**一個事實，一個表示法**——留著
布林值再加一個 `kind` 會是 §15.4 的兩份拷貝。頁面照 `kind` 給三種顏色的橫幅，紫、琥珀、綠。

#### ASR 這條路終於有生產呼叫端

票面點名的：「否則 ASR 那條路會變成下一個『造好沒接線』的東西」。`OpenAITranscriber` 從 M2
就在那裡，零個生產呼叫端。現在 `--audio` 會讓頁面出現語音上傳，轉錄結果變成 `said`。

**預設關**，因為它花的是訪客自己帳號的錢。`--audio` 沒有配 `--demo` 會被拒絕而不是默默無效。

`wav_to_pcm` 放在 `asr.py`，`pcm_to_wav` 隔壁 —— 編碼方式已經在那裡了，而且那讓 demo 模組不用
import numpy，「零新相依」那條 AST 測試才能繼續維持最嚴格的版本（stdlib ＋ `misty_agent`）。
同理 `decode_image` 放在 `app.py`，cv2 已經在那裡。

#### §16.31 那個「誠實的侷限」解除了

「五份 golden 沒有任何一份會點燈或動手臂，所以那張圖上燈永遠是暗的」—— 我當時寫「狀態圖要
活起來，靠的是 #10 餵真實輸入之後跑出來的 Episode」。跑了：一次真的 Episode 之後，面板寫的是
`moves here: chest light, arms, face`，胸口是青色的，手臂舉起來，臉是笑的。

### 16.43 上一次執行的結果，留在下一個範例的畫面上（M8 #10 review）

Spec 軸把頁面當成一個人在用，走了一條我沒走過的路：**先跑一次自己的（沒有 key），再點一個
內建範例**。結果是一個紫色的「This is a specification, not a recording」橫幅，上面掛著
「Someone 52cm away, looking at the camera.」和整段紅色的沒有 key 說明。

`load()` 會重設橫幅、機器人面板、moves 說明、選單按鈕 —— 它**不會**重設感知那一行和那段紅字，
因為那兩個是 #10 才加的，而 `load()` 是 #08 寫的。**這正是票面第七格要防的那個混淆**，而且是
用我自己剛加的東西造出來的。

### 16.44 那段「怎麼給 key」的說明，有一半在頁面上做不到（M8 #10 review）

`MissingApiKey` 講兩條通道（§16.24 才剛讓它兩條都講），而頁面沿用它 —— 但那段話是寫給**站在
終端機前面的人**看的。`load_api_key` 讀的是**這個行程**的環境變數，所以訪客在自己的 shell 裡
`export` 永遠不會傳到一個已經在跑的 demo；檔案那條會，下一個 request 就讀到了，什麼都不用重啟。

Spec 軸實際驗證過：把 `OAI_CONFIG_LIST.json` 丟進 demo 的工作目錄，`storyboard` 立刻從 `null`
變成一次完整的 Episode，沒有重啟。

修法是**補一句，不是寫第二份**：`ONLY_ONE_REACHES_A_PAGE` 說明哪一條到得了、另一條要重啟。
§16.24 的「一段說明，一個地方」沒有被破壞 —— 加的是一件那段說明不知道的事（它不知道自己被
一個網頁引用了）。

### 16.45 `--demo` 拒絕 `--journal` 的理由已經過期（M8 #10 review）

那句話是 #08 寫的：「`--demo` 只是重播已經跑完的 Episode」。**#10 之後它會跑活的。** 訊息還在
講一個不再成立的理由。

真正的理由是別的，而且和 #06 有關：**一個 Journal 檔案裝一次 Episode**，而頁面上想點幾次就
點幾次。改成講這個。

### 16.46 兩軸在同一張票上抓到的其他東西（M8 #10）

- **`Any` 被用了但沒有 import。** `from __future__ import annotations` 讓它在 import 時不會
  炸，但 `typing.get_type_hints` 一叫就 `NameError`。這個 repo 沒有 ruff / mypy，所以沒有
  工具會抓到 —— 只有讀的人會。
- **12 個 mutation 活了 9 個。** 我自己跑的七個全都集中在「這條新路走不走得通」，而
  **沒被我碰到的地方一個都沒被測到**：`wav_to_pcm` 完全沒有直接的測試（雙聲道平均、16-bit
  防護都可以拿掉）；`serve(audio=...)` 到不到得了 handler 沒人測；`validate=True` 沒人測。
- **觸發種類是猜的。** `"visual" if seen is not None and not said else "speech"` —— 兩個方向
  的反轉**都**通過全部測試。而「用了哪個輸入框」是**頁面知道、伺服器不知道**的事實，所以現在
  是頁面送過來、伺服器對照 `TRIGGERS` 驗證。
- **`simulated_session` 只有一個呼叫端，而它住在 composition root 上。** Standards 說那是
  Divergent Change。修法不是搬走，是讓 `main` 也用它 —— 現在指令列和瀏覽器**穿過同一套組裝**
  抵達模型，`_robot_and_room` 整個刪掉。
- **`validate=True` 的測試本來測不出東西。** `b64decode` 預設會把字母表外的字元**掃掉**，所以
  「一張真的圖片後面接四個驚嘆號」會安安靜靜解碼成功。我第一版用的是兩種寫法都會炸的垃圾，
  證明不了任何事。
- POST 現在有大小上限。一個把 body 解進記憶體才開始看的路由不該沒有邊界。

### 16.47 M8 收尾：§16.3 那張表空了

| 東西 | 生產呼叫端 |
|---|---|
| 系統提示 | `app.py` / `react.py`（#03） |
| `load_api_key` | `app.py`（#04） |
| `JsonlFile` | `app.py`（#06） |
| `EmergencyStop`、`ToolContext.ears` | M7 #12，#05 讓真驅動那條也接上 |
| `OpenAITranscriber` | `app.py`（#05 的真驅動）與 `demo/`（#10 的語音上傳） |

M8 開始時的實質理由就是這張表（§16.3）。十張票之後它是空的，而且每一格都有兩軸 review
驗證過的呼叫端。

### 16.48 Social runtime 將預設 Turn cap 從 8 改為 12

`.scratch/social-react-runtime/spec.md` 把 12 定為新 runtime 的初始 Turn 上限。這推翻 §15.19
為 M7 單次 Episode 選的 8，而不是可同時保留的兩個預設值：`Settings` 只能有一個 default，
`SocialAgentRuntime` 也刻意沿用同一個 bounded ReAct core。因此實作與
`episode_hits_the_turn_limit.jsonl` 一起改為 12 Turns；golden 新增的四個 Turn 仍逐項遵守
「只有 model latency 與 Tool sleep 推進 fake clock」的既有規則。這是 golden 規則第六次被
觸發，選擇讓 golden 配合已批准的新架構規格。

12 仍不是硬體量測值。本專案沒有 Misty II；只有後續 Journal 與 replay 證據能支持再次調整。

### 16.49 Demo 首頁改以三個社交情境說明 runtime（ticket 01 follow-up）

舊首頁把 Journal failure modes、`Play` 與需要 API key 的 `Run` 放在同一層。它雖然能重播紀錄，
但訪客無法從畫面判斷哪個動作真的會執行、為什麼沒有 key 還能 Play，也看不出這是一個社交機器人
專案。首頁因此改成白色、內容優先的三張橫向圖卡：有人問候 Misty、有人哭泣、A 聊完後切換到 B。

三張卡的主按鈕只有一個：`執行離線模擬`。它們都 POST 到具名 scenario route，穿過
`SocialAgentRuntime`、bounded Episode 與 typed Journal，再把 runtime records 與 Journal 當成
可展開的工程證據。Live AI 被移到獨立的次要區塊，清楚標示 API key 要求；不再用一個無法解釋的
Play/Run 差異暗示兩條路具有相同能力。

其中只有 greeting 是 ticket 01 已具備的 Explicit Request 垂直路徑。哭泣情境直接注入 visual
Care Cue，A/B 情境直接注入人物標記並開兩個獨立 Episode；頁面與 payload 都必須說明這兩者**沒有**
做哭泣辨識或人物辨識。這些案例驗證 runtime 能否接住已選出的 cue 和維持 Episode 邊界，不是感知
能力或真機行為的證據。本專案仍沒有 Misty II，三個案例都只使用 scripted model、fake clock 與
simulated robot。

### 16.50 Demo 必須區分「剛執行」、「scripted」與「尚未實作」（ticket 01 follow-up）

§16.49 把三個社交情境放上首頁後，仍留下更根本的混淆：三張卡都能 Run，使預先注入的哭泣
Care Cue 與 A/B 標記看起來像已完成能力；問候案例執行後又只把 `1 Episode`、
`5 Runtime records`、`input_exhausted` 放在主畫面，訪客看不見 Misty 選了哪個 Tool、說了什麼，
也無法分辨這是歷史紀錄、即時 LLM，還是 scripted test double。

Demo 從此遵守以下展示契約：

- **已完成且可執行**：Run 必須穿過目前程式的生產 seam，畫面從這次回傳的 runtime records 與
  Journal 衍生輸入、Cue、Tool choice、simulated effect 與結束結果；不得拿手寫的預期步驟冒充結果。
- **Scripted provider**：可以作為 deterministic acceptance evidence，但必須在結果旁直接說明模型
  決策是預先定義的；它證明 orchestration、Tool dispatch 與 Journal，不證明 LLM 自主決策。
- **尚未實作**：可以作為 roadmap preview 留在情境卡上，但沒有 Run route。哭泣案例等 ticket 06，
  A→B handoff 等 ticket 08；在那之前不能用注入 cue／actor 的腳本把卡片假解鎖。
- **歷史 replay**：若未來保存一次驗證結果，必須帶來源 commit、測試或 Journal provenance，並與
  「剛剛執行」分開標示。手寫 fixture 不得稱為過去真實執行。
- **兩層語言**：主結果用「人說了什麼、系統判定、Misty 選擇、模擬回應、情境執行完成」；
  `Episode`、record count、typed ending 與原始 Journal 收在工程細節。`Decision Note` 到 ticket 02
  才存在，ticket 01 不得把 Tool choice 包裝成私有思考或 chain-of-thought。

因此 ticket 01 follow-up 只解鎖 greeting。每張後續 ticket 若有 Demo acceptance criterion，完成時
同時交付人可讀的可觀察成果與同 seam 的 tests；不需要等所有 tickets 完成才看得到 UI 變化。

### 16.51 Trigger Evidence 與 model protocol 是同一條可追溯鏈（ticket 02）

Ticket 02 把 Episode 第一個 Turn 的鬆散 `{trigger, said}` 改成 typed Trigger Evidence。它攜帶
來源、runtime-relative time、selected facts、transcript、不確定性與可選的 bounded selected
image；這份 Evidence 在任何 Observation 之前交給 model，而 Tool 完成後取得的 cheap Snapshot
仍只屬於 Observation。兩者不得互相冒充。Selected image value type 本身驗證 strict base64 並限制
decoded bytes 為 8 MiB；Episode 完成後的 RuntimeResult 只保留 MIME metadata，不再持有圖片 bytes。

Model Interface 使用 provider-neutral 的 native function-calling message shape。正式 OpenAI adapter
保留 assistant Tool call identity，並以 matching `tool` role result 接回下一個 Turn；request 明確
停用 parallel Tool calls。provider 若仍在同一 Turn 回傳多個 calls，該 Turn 明確失敗並讓 bounded
Episode 以 error 結束，不能只取第一個。selected image 只由 adapter 在最後一層轉成 provider
格式，runtime、ReAct 與 scripted scenario provider 都不需要知道 OpenAI。

每個 Decision 可附帶最長 240 字的公開 Decision Note，說明下一個 Tool choice 的直接目的。Note
是 typed Journal record 並可由 Storyboard／Demo 重播；它不是 private reasoning，不要求或保存
chain-of-thought，也受 §4 的 control-parameter guard 約束。Demo 問候案例的輸入與 Decisions 仍是
預先定義的 scripted fixture，但 Trigger Evidence、native context、Tool dispatch、Observation、
Decision Note 與 Journal 都是按 Run 後由目前程式重新產生。圖片只作為明確 request 的 selected
Evidence；autonomous visual cue classification 仍屬後續 tickets。

Review 也收緊了三個接縫：Cue 與 Trigger Evidence 共用 input 抵達時的同一個 runtime timestamp；
`Session.episode()` 與 `run_episode()` 只接受 typed Trigger Evidence，不再各自保留 trigger string
compatibility branch；Decision Note 驗證失敗會記為 model-phase `ExecutionFailed`，並以
`EpisodeFinished(outcome="error")` 封口，而不是讓例外逃到 Runtime 外層。

### 16.52 Active Attention 採 Turn-boundary cooperative scheduler（ticket 03）

Ticket 03 不在 Runtime 另開 background thread。`InputSource` 負責保存它已觀察到的 input，並在
交付時回報已等待的 age，而非要求 provider 與 Runtime 共用 absolute monotonic clock domain；
`SocialAgentRuntime` 在 idle 時做 blocking read，在 active Episode 每個 Tool 完成後的安全 Turn
boundary 以 non-blocking `read_available()` 收走已抵達的 input。這讓 scenario 能保留真正的抵達
timestamp，又不會在 physical Tool 中途任意搶走控制權。未來 live adapter 可以在自己的 driver
邊界收資料，但同一時間仍只有一個 Episode 能呼叫 model 或產生 robot effects。

Cue scheduler 的初始政策固定且可測：queue capacity 預設 3、freshness 預設 5 秒；個別 Evidence
可以宣告更短期限。Explicit Request、Care Cue、Social Invitation 的 priority 分別是 3、2、1，
同 priority 依抵達順序。相同 deduplication key 的同級或較低級新 Cue 被合併；較高級新 Cue 取代
舊 Cue。queue 滿時只有較高 priority 能淘汰最新的最低 priority Cue，否則丟棄新 Cue。每次
enqueue、dedupe、replacement、overflow／expiry／shutdown drop 與 dequeue 都留下 typed Runtime
record；Runtime 或 Episode error 也會先為剩餘 Cue 記下 typed drop reason。只有仍 fresh 的 Cue
能在前一 Episode 完成後開新 Episode。

Demo 仍維持三張社交情境卡，且哭泣辨識與 A→B target handoff 仍鎖在 ticket 06／08。已解鎖的
問候案例加入同一匿名人物在第一個 Episode 忙碌時出現的 scripted cues，直接以本次 Runtime
records 顯示 active cue、queue 上限、priority、去重、升級、overflow、expiry 與 dequeue。這證明
排程與單一所有權，不證明人物追蹤、真 LLM 自主決策或真機行為。

### 16.53 Wake phrase 在外部 AV provider 內完成 gating（ticket 04）

Ticket 04 採用 ADR 0004 的外部喚醒方案。`LiveInputAdapter` 在 `InputSource` 邊界內擁有本機 wake
gate、單次 bounded capture 與 hosted-ASR 決策；`SocialAgentRuntime` 與 Episode 只看 typed input，
不認得 PocketSphinx、PCM 或 provider timeout。正式組裝仍共用 Misty 的單一 AV session，但
`AudioStream` 只產生 VAD `Segment`，不再在 producer thread 對每段 ambient speech 呼叫 hosted ASR。

`Hey Misty` 與 `Hi Misty` 由 PocketSphinx 5.1.1 的本機 JSGF grammar 判定。這個選擇是可替換的
`WakeDetector` seam，不是準確率聲明：threshold 只在 checked-in synthetic macOS voices、三種語速與
一個 false-trigger control 上驗證；真實房間、真人、Misty 麥克風與 vendor AV 行為全部仍是
hardware-unverified。Misty 內建 wake recognition／sound direction 不啟用，因為它們和持續 AV
streaming 的資源互動無硬體可驗證。

喚醒只授權一段 utterance。等待受 `silence_timeout_s` 限制，PCM 受 `max_utterance_s` 限制，decoded
block 與 VAD segment queues 分別有固定 capacity；滿載時保留較新的工作並以 typed backlog record
揭露丟失。重複 wake、無 request 的 silence ending、ASR empty／timeout／error，以及 decoder EOF／
failure 也各自留下 typed Runtime outcome；audio failure 最後收斂成 `runtime_error`，不偽裝為正常的
`input_exhausted`。Hosted ASR 關閉 provider retry，使設定的 timeout 成為單次
授權 attempt 的總上限。只有成功且非空的 transcript 會連同 wake phrase、confidence、detector、
capture ending 與 runtime-relative wake time 形成 Explicit Request Trigger Evidence，進入第一個 Turn。

Demo greeting card 提供四個 synthetic WAV 選項。每次 Run 都真的重新執行本機 WAV decode、VAD、
wake detection、Runtime、Tools 與 Journal；為保持 no-key/no-network acceptance，ASR transcript 與
model Decisions 是明確標示的 scripted providers，robot effect 是 simulation。主流程直接顯示 wake、
capture、ASR、Episode、Misty 回應與 ending；Ticket 03 的 queue evidence 仍由後續 scripted Cues 保留。

### 16.54 Social Invitation 由本機 temporal visual gate 篩選（ticket 05）

Ticket 05 在共用 `InputSource` seam 加入 `VisualInputAdapter`。Provider 只把本機 detector 的人物框、
是否面向相機、手部位置與 confidence 交給短期匿名 tracker；不保存身分、不推論情緒，也不把單張
still image 稱為揮手。第一版 Social Invitation 必須在同一 anonymous track 上同時滿足持續注視、
足夠的水平手部位移與方向變化。空房、沒有看向 Misty 的路過者和只有手部位移但注視中斷的情境
只留下 typed visual-attention records，不開 Episode，也不呼叫 model。

Visual gate 只判定「是否有足夠 evidence 值得詢問 model」，不指定回應 Tool。形成 cue 時只選目前
frame 的一張 bounded JPEG crop 進入既有 multimodal Trigger Evidence；所有週期性 raw frames 都停在
provider 內，完成後 Runtime result 仍只保留 MIME metadata。Model 可以選低風險 `speak`／
`look_around` 或直接 `done`，這張票不加入 approach。

Demo greeting card 延續原本三張橫向主卡，在卡內同時提供四段 synthetic WAV 與四組 synthetic
visual timelines。每次 visual Run 都重新執行匿名 tracking、temporal gate、Runtime、model stub、
Tools 與 Journal；frame signals 與 model Decisions 明確標示為 scripted。畫面直接列出每一 frame 的
gate outcome/facts、selected Evidence metadata、Decision Note、模擬回應與 ending；negative fixture
則清楚說明 gate 為何保持安靜以及 model 未被呼叫。MediaPipe detector 是本機可替換實作，但真實
相機準確率、threshold calibration、人物關聯、延遲與 Misty II 全部仍是 unverified；本票只用
synthetic temporal fixtures 驗證 orchestration，不構成硬實機證據。

### 16.55 Care Cue 保留不確定性，回應仍由 ReAct 決定（ticket 06）

Ticket 06 延伸同一個 `VisualInputAdapter` 與 anonymous tracker，不建立第二條情緒辨識 pipeline。
本機 detector 只輸出 normalized bounds、confidence，以及可觀察的縮眼、張口、低頭、嘴角抬高
geometry。Care gate 必須在同一 track 上跨至少三個 frame、持續達時間與平均 confidence 門檻才形成
Cue；Trigger Evidence 只描述這些 signal、持續時間與不確定性，不含 emotion classifier label、
「正在哭」或心理診斷。單張 frame 與最後一張高 confidence 都不能補救不足的 temporal evidence。

Gate 仍只回答「是否值得交給 model」，不把 Care Cue 映射成 approach、安慰台詞或固定 Tool sequence。
同一份 Evidence 的 scripted acceptance 分別證明 model 可以直接 `done`、呼叫便宜的
`observe_target`，或選擇較昂貴的 `inspect_scene`。兩個 active-perception Tool 都回傳 typed kind、
cost、ending、age、freshness、structured facts 與 uncertainty；沒有可用 track 時回 typed
`unavailable`，不擴張每個 Turn 都附帶的三欄 Snapshot，也沒有移動權限。
Session 在 Episode 開始時依 Trigger Evidence 的 anonymous track 建立固定 perception view；後續
Turn-boundary drain 形成的 queued cue 不得改寫它。目標不在最新 frame 時，以該 track 自己的
last-seen time 回 unavailable/age，不得用別人的新 frame 把舊 detection 冒充成 fresh。

Demo 將原本鎖住的 care 卡解鎖，卡內提供「持續可觀察 signal」及「表情 geometry／本人言語衝突」
兩組 synthetic timelines。後者在第一個 perception Tool 後由 Snapshot 收到本人明確表示難過，
scripted model 的下一個 Turn 尊重這句話並承認視覺線索可能不準。畫面由當次 Runtime records 與
Journal 顯示 Evidence、Decision Note、感知／互動 Tool、Observation 和 ending；detector signals、
model Decisions、後續 speech 與 robot effect 都明確是腳本／模擬。MediaPipe geometry extraction
存在，但 threshold、真實哭泣辨識、真人／真相機準確率與所有 Misty II 行為都未驗證；這不是情緒
辨識準確率聲明。

### 16.56 Skills 是按需讀取的指引，不是另一個執行器（ticket 07）

`SkillCatalog` 與 `ToolRegistry` 分離。第一個 Turn 只收到有效 Skill 的 name/description；
`activate_skill` 才讀完整指引，`read_skill_resource` 才讀 references 或 UTF-8 text assets。
這兩個 capability 仍經單一 typed Tool schema/validation/dispatch，內容放在 matching Tool result
供同一 Episode 後續 Turns 使用。每次 Episode 新建 activation permissions，所有結束方式都不保留
它們；不把 Skill instructions 寫入跨 Episode memory。Journal 保留當次 discovery 與 Tool 結果，
Storyboard 每個 Moment 顯示 active Skills，終止 Moment 清空。這是執行證據，不是下一場的 context。

使用 PyYAML 的 SafeLoader 子類處理常見 frontmatter，拒絕重複 key、無效 name/description 與空內容。
每份文字上限 64 KiB，拒絕 symlink、越界路徑、非文字資源與 scripts。第一版 assets 只支援 UTF-8
文字，不執行任意程式、下載網路 Skill 或建立 nested agent。新增合規 Skill directory 不改 ReAct
core 或 Tool Registry；invalid Skill 不進 discovery，嘗試 activation 時明確回傳 refusal。

`listen` 補上原本沒有的 bounded active listening，預設等待五秒、上限三十秒，由 config 控制，
不擴張 cheap Snapshot。模擬時消費真正按時間抵達的 scripted utterance；live provider 共用唯一 VAD
queue，明確 listen 授權一次 ASR、不需要再 wake，且不搶既有 pending wake。聆聽回傳 typed ending、
source、age/freshness 與不確定性；transcript queue 的 age 明列為 dequeue age 而非 capture age。
等待會檢查 stop，hosted ASR timeout 不得超過剩餘聆聽預算。真機收音與 speaker attribution 未驗證。

Demo 保留三張橫向卡，「關心」卡加入共用 `CALMING_SUPPORT` 的「請協助我冷靜」文字情境：
activate → read reference → speak → listen → gentle head expression → speak → done。Run 當下真的
執行 Skill 載入、Runtime、Tools 與 Journal；model Decisions、後續話語仍是預先編寫的 fixtures，
不是過去真 model 的輸出，也不證明模型自主採用指引的品質。畫面與文件持續明示 scripted／simulation；
未呼叫付費模型，沒有 Misty II，沒有任何實機成果。

### 16.57 一個 Episode 一個匿名 Interaction Target，交接只在 Turn boundary（ticket 08）

`InteractionTarget` 在 `Session.episode()` 從 Trigger Evidence 建立：有 `track_reference` 就綁定
該匿名 track，純語音則為 `unobservable`。同一 reference 同時交給 active perception view，因此
`observe_target`／`inspect_scene` 只會回報那條 track；更近、更大或更新的臉在 tracker 裡是另一條
track，對本 Episode 只呈現為 `unavailable`（`lost`），同一 track 回來才是 `reacquired`，TTL 過後
同位置的新臉是新 reference，不算重新取得。Tool result 與每個 Snapshot 都附上 target 的
reference 與狀態；`approach` 對 `lost` 的 target 直接回 `target_lost`，不依舊 reading 前進。
Journal 新增 `target_bound`（Episode 起點）與 `handoff_requested`（Turn boundary）。

§15.4 的「Snapshot 恰好三個事實」在此修正為三個感知事實加一個 Episode 狀態事實：target 不需要
任何感知呼叫，附上不增加每個 Turn 的成本；`target` 為 `None` 時 JSONL 不寫出，舊 golden 逐字
不變。

交接：Episode 進行中 B 的 Explicit Request 由既有 cue queue 保存；`collect_available` 在 Turn
boundary 回傳一次 `HandoffNotice`，loop 記錄並以 system message 告知 model 收尾後 `done`。
「另一個人」只由匿名 track 判定：排隊 cue 的 `track_reference` 存在且不同於 active target 才通知；
沒有 track 的 explicit request 依規格第一版假設視為目前對話者，不通知，但之後仍各自開 Episode。
`approach` 對 lost target 回傳既有的 `lost_user`（§15.4 的四個 status 不增），以 target 區塊區分。
Runtime 不會為了交接結束 Episode；bumper／e-stop／shutdown 仍立即中止。B 的 cue 沿用 freshness，
A 太久就 `expired`，不強行互動。B 的 Episode 從新 Evidence 綁新 target，不繼承 A。

Demo 第三張卡改為可執行：`A_THEN_B` 與 `B_EXPIRES` 兩個文字腳本，actors 為 A／B，發言歸屬由腳本
用 `track_reference` 指定並在 uncertainty 與 provenance 明說「沒有聲源方向、沒有人臉身分」。
執行流程改為依 cue lifecycle records 順序呈現所有 Episodes：Episode 進行中收到的 cue records
放在該 Episode 的 handoff 通知處，其餘接在 Journal 之後。問候卡因此也會顯示它原本就有的四個
Episodes 與排隊事件，而不再只顯示第一個。

### 16.58 一個 Robot Interface，兩個 Adapter，沒有第二份紀錄（ticket 09）

`misty_agent/robot/` 定義 `Robot` Protocol：`speak`、`display_image`、`move_arms`、`move_head`、
`change_led`、`play_audio`、`drive`、`halt`，一律回傳 typed `Effect(ok, detail)`。Tools 與
`control.approach` 只看 `Effect.ok`，不再讀 status code；vendor 參數名（`linearVelocity`、`timeMs`、
`units`）只存在於 `RealMistyAdapter`，它把行為轉成既有 `RobotCommands` 的 request，request shape 由
原本的 contract tests 經 `RecordingCommands` transport 釘住，整個 adapter 標示 hardware-unverified。

`SimulatedMistyAdapter` 取代 `MovingWorld`：同一物件既是 Robot 也是 reading source，保存 pose（表情
asset、LED、頭、手臂）、最後說的話與音效、halted，以及被量測的距離；`failing` 可讓指定行為回傳失敗且不改
狀態，於是 Observation 出現 `ok: false`，Storyboard 也不再套用該動作（此前 Tool 一律回 `ok: true`，
失敗路徑從未走過）。Storyboard 的 `RobotState` 即 `RobotPose`，仍從 Journal 推導，不讀 robot 物件。
不存在 RecordingRobot：`RecordingCommands` 只是測試用 vendor transport，不進 production 組裝。

測試遷移：原本直接把 `RecordingCommands` 當 robot 的測試改為 `RealMistyAdapter(RecordingCommands())`，
request 斷言改經 `robot.commands`；world 測試改用 `SimulatedMistyAdapter` 的狀態（`directions`、
`halted`）而不是 request log。同一個 scripted Episode 在兩個 adapter 上跑出相同的 ToolCalled／Observation
序列，且 real adapter 的 endpoints 與 simulated pose 各自符合預期，這是「同一條 Tool/controller code
path」的證據。Demo 的 run payload 附上模擬 robot 的最終狀態，並以測試確認它與 Journal 推導的 pose 一致。

### 16.59 approach 先對準底盤，再以有界 Step 靠近；沒有 bearing 就不動（ticket 10）

`DistanceReading` 增加 `bearing_deg`（相對底盤 heading，左為正）與 `uncertainty`。`control.approach`
每輪取一次新鮮讀數，然後只做三件事之一：|bearing| 超過 `align_tolerance_deg` 就轉底盤（單次上限
`max_turn_deg`，再除以 `max_actual_motion_multiplier`，讓轉過頭的機器人也不會擺到另一側容差外）；否則
依既有 `plan_step` 前進或後退一個有界 Step；或以 typed status 結束。頭部 yaw 完全不參與。每個 Step
後必須有新的 Reading 才能繼續，這一點沿用原本的 freshness epoch。

Status 拆開：`lost_user`（等待結束時完全沒有讀數）、`stale_reading`（一直有讀數但沒有一筆夠新）、
`bearing_unavailable`（來源說不出方向；live `DistancePipeline` 只有距離，因此真機路徑 fail closed）、
`alignment_failed`（轉向預算用完）、`step_limit`（Step 上限，原本與 `timeout` 混用）、`timeout`
（wall-clock）、`drive_error`。`ApproachResult` 帶 `rotations`、最後讀數與其 `uncertainty`、以及 `motions`（每個動作的種類、
量與決策時的距離／bearing；不叫 trace、不叫 turns，那兩個詞在 CONTEXT.md 另有所指），Tool result 原樣傳給 model 與 Journal；schema 仍無參數，描述不含
距離或速度詞彙。`steps` 現在含轉向；公開形狀由 `ApproachResult.as_tool_result()` 在 control 層決定，因此 Journal 的 Steps 與 adapter 實際下達的 drive 數仍相等。

`SimulatedMistyAdapter` 有 `heading_deg` 與相對極座標的人：角速度轉底盤並反向改 bearing，線速度沿
heading 平移後重算距離與 bearing。轉速 `deg_per_sec_at_percent` 與 `turn_percent` 和既有平移常數一樣
標示 UNCALIBRATED；`align_tolerance_deg`、`max_turn_deg`、`max_align_steps` 為 simulated design values。
模擬 world（測試、harness）在讀數上明說 bearing=0「aligned by construction」，符合規格「模擬模式可由
scenario 明確提供 safety state」；`a_reading` 預設如此，直接建 `DistanceReading` 的地方則沒有 bearing。

Goldens：`episode_ends_after_several_turns` 與 aborted 兩檔的 approach result 多了 `rotations`、
`distance_cm`、`bearing_deg`、`uncertainty`、`motions`，status 與 steps 不變；讓步的是 golden，理由是 ticket 10 要求
typed result 攜帶這些欄位。Demo 問候卡新增「過來陪我」文字腳本（人在 150 cm、bearing 25°），流程顯示
controller 結果、每個 Step 的種類與決策讀數，robot 狀態顯示 heading 與未被動的 head yaw。

### 16.60 movement checkpoints：stop、hazard、fail closed（ticket 11）

`control/safety.py` 定義 `HazardReading(blocked, observed_at, uncertainty)`、`HazardSource`、fail-closed
的 `NO_HAZARD_SOURCE` 與只供模擬的 `ALWAYS_CLEAR`。`approach()` 多了 `stop` 與 `hazards`：第一個動作前、
每個動作前後，以及動作進行中每 `movement_poll_s` 都做一次 checkpoint。stop → `aborted`（不再下任何
指令；halt 由 stop 的擁有者 `EmergencyStop` 早已送出）；hazard blocked → controller 呼叫 `halt()` 並回
`blocked`；沒有讀數或讀數老於 `hazard_max_age_s` → `hazard_unavailable`，不動。所有結果附 `reason`。
動作中的 checkpoint 讓 halt 落在 hazard 出現後一個 poll 內，測試以時間斷言這一點，少一個 checkpoint
就會被抓到（negative control）。

真機 Session 沒有 hazard 來源（vendor HazardNotification 尚未接，且無硬體可驗），因此 movement Tool
在第一個 checkpoint 就 fail closed；`SimulatedMistyAdapter` 由 `Placement.hazard_at_s`／`leaves_at_s`
提供情境時間線。測試與 harness 的模擬讀數來源明確傳 `hazards=ALWAYS_CLEAR` 或世界本身，符合規格
「模擬模式由 scenario 明確提供狀態」。Demo 問候卡新增「途中人離開」與「途中出現障礙」兩個腳本。
Goldens 的 approach result 多 `reason`，status 與 steps 不變。`hazard_max_age_s`、`movement_poll_s`
為 simulated design values；本節與測試皆不是真機 safety certification。

補記（ticket 11 review）：`checkpoint("after a motion")` 與 `wait_through` 最後一個 poll 落在同一個時刻，
是重複的檢查，已移除；「每個 Step 後」的檢查就是動作結束時的最後一個 poll。動作中被停下的 motion 在
`motions` 標記 `interrupted=True`，`steps` 仍計入（Journal Steps 必須等於 adapter 收到的 drive 數），
reason 改說「during motion N」。`RobotAdapter` Protocol 明列 `halt`。aborted golden 改回報 `aborted`：
以前 `is_aborted()` 沒把 stop 交給 ToolContext，controller 只能等到 deadline 回 `timeout`；現在測試
與 production 一樣把 stop 接進去，golden 讓步。`HazardReading` 改名 `HazardState`，避免與 CONTEXT.md
的 Reading 混用。

### 16.61 Episode 內保留、Episode 間清除；持久化邊界另行去識別（ticket 12）

本票以已核准的 social-runtime spec 反轉 §15.5／§15.26 的舊 M7 memory 設計。`run_episode` 的
`working_context` 本來就保留本次 Trigger Evidence、native Tool call、matching Tool result、Snapshot、
後續 transcript 與按需載入的 Skill instructions；它現在是唯一的社交脈絡。函式返回後整份 local list
釋放。`Session` 與 `run_episode` 不再接受 Memory dependency，舊的 exchange／summary／facts store、
相關設定與 `speaks` bookkeeping 一併移除，因此另一個 Episode 沒有可誤接回 A 個人資料的 injection
point。Interaction Target 與 `EpisodeSkills` 仍每 Episode 新建。A→B acceptance 由 hosted-model seam
的實際 request 證明：A 的後續 Turn 看得到 A 的名字與 listen transcript，B 的第一個 request 只含 B
自己的 Trigger Evidence，不含 A 的名字、話語、Skill instructions 或 summary。

「不保存」只限制 persistent storage，不禁止當次 in-memory processing，也不等於完全離線。
configured hosted ASR／VLM／LLM 仍可收到完成當次決策所需的 bounded selected Evidence；raw periodic
frames、完整媒體與前一個 Episode 的個人脈絡不跨過該 boundary。Runtime result／in-memory Journal 可供
當次 Demo 顯示；圖片 bytes 仍在 completion summary 移除，Demo 不建立 server-side run session，所有
HTML／JSON 回應加 `Cache-Control: no-store`，refresh 必須重新執行而不從 HTTP cache 恢復舊 payload。

`JsonlFile` 是唯一 production persistent Journal subscriber，現在預設把 Decision Note、Tool 文字、
listen transcript、Snapshot `new_speech`、拒絕與 failure prose 換成明確 redaction marker（Snapshot speech
則為 `None`），同時保留 typed control-flow、已通過 registry 的 Tool 名、封閉集合內的
structural enum value、timing、target token 與數值 Observation。未通過 registry 的 rejected Tool 名、
subscriber 名與例外文字也遮蔽；開放 mapping 不能只因 key 叫做 `status`、`source` 或
`result` 就繞過去識別，未列入持久 schema 的 mapping key 也會改為無意義的序號欄位。
純 `to_jsonl` 仍是 lossless serialization，只供有 provenance 的 synthetic／licensed fixtures 與
goldens；兩個介面刻意分開，避免測試資產需求放寬 real-user policy。

A→B Demo 卡升到 ticket 12，當次 flow 由實際 Evidence／Journal 推導「Episode 內保留」與「Episode
間清除」兩個 Moment。它仍是 scripted text actors、scripted model 與 simulated robot；沒有聲源方向、
face identity、真實 LLM 輸出或 Misty II 證據。Cue queue 的可觀察 records 只有 run-local cue id、匿名
track／priority／timing／queue size；ticket 13 的 refusal suppression 也只能沿用匿名短期狀態，不能
重新引入 personal memory。ADR 0003 記錄這個預設；未來若要長期 profile，必須另做 consent policy。

### 16.62 尊重明確拒絕，並以短期匿名 Cue Suppression 避免重複打擾（ticket 13）

Runtime 不以關鍵字解讀「不要靠近」。Persona 要求 model 在對方明確要求空間時
停止追問與後續接近；model 可先用任意簡短、合宜的話回應，再選擇 typed
`respect_boundary` Tool。該 Tool 呼叫共用 `Robot.halt()`、結束 Episode，並在
`EpisodeOutcome` 留下 `boundary_respected` typed fact；沒有固定台詞或另一條回應 pipeline。

`SocialAgentRuntime` 只在該 outcome 之後建立 suppression，狀態只含 run-local anonymous
track token 與 `cue_suppression_s` 截止時間。同 track 的 Care Cue 或 Social Invitation
在到期前留下 `cue_suppressed`、不開 Episode；不同 track 不受影響。新 Explicit
Request 留下 bypass record、移除 suppression 並立即進入排程。TTL 以 fake clock 的
`now >= expires_at` 為清除邊界；視覺 gate 回報空場景、Runtime shutdown 或 run 結束也都
留下 typed clear record 並釋放狀態。

Care Demo 的 `respect-boundary` 文字 fixture 在同一次當前程式執行中顯示：model 的
簡短回應、`respect_boundary`、controller halt、30 秒倒數、被抑制的非明確 cue、以及
後續 Explicit Request 繞過。話語與 model decisions 是明確標示的 scripted fixtures，robot
是模擬；專案仍無 Misty II，halt 行為沒有真機驗證。

補記（ticket 13 review）：suppression 狀態改由 `_CueSuppressions` 持有，anonymous token 的讀取只有
一個出處（handoff 通知也改用它）。Track 消失的判定原本是視覺 gate 任何一個 EMPTY notice 就清掉全部
suppression；但 gate 對每個沒有偵測到人的 frame 都會發 EMPTY，所以那等於「對方轉頭一下」就解除節流，
正是這張票要防止的重複打擾。改為必須持續空景達 `track_lost_after_s`（預設 1.0 秒，SIMULATED，對齊
本機 gate 自己的 track TTL）才算離開。曾短暫加入「只清視覺 track」的區分，後來拿掉：production 的
anonymous token 一律由視覺 gate 產生，audio-only track 根本不會有 token，那個區分無法成立。

`respect_boundary` 會 halt，但 ends_episode 的 Tool 原本不寫 Observation，於是 halt 成敗完全不進
Journal，Demo 也就無從誠實呈現。改為：ends_episode 且有 result 的 Tool 在收尾前記一筆 Observation
（含 Snapshot）。`done` 回傳空 result，因此不記、goldens 逐字不變。Demo 依實際結果顯示「已發出 halt」
或「halt 未成功」。`boundary_respected` 仍由 Tool 註冊宣告而非 halt 結果決定：對方要求空間這件事不因
馬達沒回應而改變，suppression 照樣成立。註冊時驗證 `boundary_respected` 必須同時 `ends_episode`。

Demo 的 `respect-boundary` fixture 改為兩個非明確 cue（一個在 Episode 進行中排隊、一個稍後抵達），
倒數因此真的在倒數；`_CUE_WORDING` 讓排隊與判定共用一份措辭，非明確 cue 不再被引號包成「人說」。

### 16.63 中英雙語與緊急情境界線：policy 與 Skill，不是關鍵字旁路（ticket 14）

語言與高風險回應都由 persona policy 與 `emergency-boundaries` Skill 引導 model，runtime 不看
transcript 決定台詞。persona 新增兩節：跟隨對方語言（含 Episode 中途換語言，wake phrase 仍只有
英文 Hey/Hi Misty），以及有人可能處於危險時的界線——留下來、說清楚做不到什麼、指向身邊可信任的
人或當地緊急服務；不診斷、不保證安全、不宣稱聯絡過任何人、不提供物理救援，也不編造緊急電話號碼
（不知道所在國家）。Skill 用既有 progressive disclosure：catalog 只露 name/description，指引與
`references/what-to-say.md` 按需載入。

兩條界線是結構性的，其餘是指引：registry 裡沒有任何能離開機器人的 Tool（所以「我已經聯絡了」不可能
為真），`speak` 只收 text、沒有收件者。指引可以被改寫繞過，這點在文件與測試裡都明說。

測試分兩層。`tests/boundary_audit.py` 把說出口的話讀成性質（語言、是否指向真正的求助管道、是否
說出能力限制、是否出現禁止的宣稱），`tests/test_boundary_audit.py` 逐條證明每個 pattern 都會觸發，
且不會把「我沒有辦法搬動它」誤判成違規。`tests/test_bilingual_emergency.py` 以性質斷言跑 scripted
Episodes，不比對固定句子。真模型評估沿用既有 `llm_live` marker：預設 deselect，跑起來會把語言一致率
與界線觀察印出來，只報告不 gate——coarse regex net 不適合當付費網路測試的 gate。

Demo 關心卡新增 `zh-emergency-support`（中文求助）與 `en-rescue-limits`（英文物理救援要求）。撰寫
fixture 時 speak 的 150 字上限擋下一句過長台詞，這正是 persona「一次說一件事」的規則在運作，於是
拆成兩句。

補記（ticket 14 review）：audit 原本會把「守住界線」的句子誤判成違規——「I can't promise you will
be safe」「我沒有辦法保證你一定會沒事」「我沒辦法判斷你得了什麼病」都被標記，而這些正是 persona
要求 model 說的話；被標記的會是正確答案。加上否定前綴檢查（視窗不跨子句邊界），並把這些句子放進
KEPT 迴歸清單。另外三處：「你已經聯絡到家人了嗎？」是對人的提問不是機器人的宣稱，中文 contact
pattern 改為必須以 我 為主詞；「我會等人來救你」是別人來救，rescue 的萬用字元排除 人；未來式的
「I will call someone for you」「我可以幫你打電話叫救護車」原本完全沒被涵蓋，而那正是「can you
call someone?」最自然的回答，已補上並加測試。`language_of` 改為比例判定，一個零星漢字不再讓英文
句子變成 mixed。

persona 的新句子原本只在 ticket 的測試檔以「單字」斷言，mutation 顯示把「follow them」改成
「ignore them」仍然全綠。依 test_persona.py 既有規則改為「片語」斷言，並移回 test_persona.py 與
其他 persona 主張放在一起。

ASR 原本把 `asr_language` 釘在 "en"，所以中文語音永遠不可能以中文抵達 model——checkbox 1 在真實
語音路徑上並不成立。改為預設 None 由 provider 自行偵測，且 None 時不送出該參數而非送 null。偵測
品質屬於 provider，和整條音訊路徑一樣未經硬體驗證。

測試範圍修正：原本把 display_image／change_led 也列為禁止的「移動」，但規格 scenario 11 明確允許
組合 speak/listen/expressive Tools，等於測試自創了規格沒有的規則；現在只禁止底盤移動。

### 16.64 十五個 Acceptance Scenario 收斂成一份契約，Demo 與測試共用同一條執行路徑（ticket 15）

規格列的十五個社交情境寫成 `misty_agent/acceptance.py` 的 `ACCEPTANCE_CONTRACTS`：每條指名所屬
card 與 fixture、是否允許開 Episode、Episode 數、第一個 cue 的種類、必須留下的 records（runtime
與 Journal 兩邊）、會讓結果不安全或越界的 Tools、底盤是否可動、是否必須 halt。刻意不釘台詞與
Tool 順序——社交情境本來就不只一種合理回應——但明確拒絕不安全的結果。空房間與路人兩條的
`opens_episode=False` 是全檔最強的斷言：不打擾。另外，十五條一律套用 ticket 14 的 boundary audit。

補上規格缺的三個情境：分享好消息、只說需要幫忙、不需移動的問題。

`run_fixture` 成為執行內建 scenario 的唯一路徑，Demo 與 `tests/test_acceptance_scenarios.py` 都
呼叫它；原本 `demo/__init__.py` 的 fixture helpers 移進 `acceptance.py`。這避免規格警告的「另建
平行 harness」。

Demo：picker 標出每個 fixture 對應規格第幾個情境並顯示該情境敘述、`/acceptance` 提供完整契約與
「這不是 benchmark」說明、provenance 分成 specification fixture／scripted run／live-model run
三類且一律附 hardware-unverified（scripted 與 live 兩條路徑都貼）、replay 可播放／暫停／從頭／
拖曳整場所有 Moments。

`tests/test_documentation_contract.py` 讓文件各司其職可被測試，退場說法重新出現會紅；否定句不算
宣稱，否則 ADR 0001「本設計不是 PPA」反而會被判違規。

補記（review）：第一版契約有幾條是空的——14（hazard 中止）與 8（正常接近）欄位完全相同，用 8 的
run 去跑 14 的契約會通過；13 沒有斷言第二個 Episode，handoff 等於沒被檢查；4／10／12 只要求
speak，任何會說話的 Episode 都滿足。加上 `halts`、`episodes`、`cue_kind` 三個欄位並在測試裡真的
讀它們之後，14 對 8 的 run 會紅、13 少一個 Episode 會紅、4 的 cue 種類錯會紅。另外補上：契約寫錯
Tool 名字會被 registry 比對抓到（原本拼錯等於靜默關閉該條）、entry-point 測試不再把 app.py 排除
在外（原本排除的正是最可能出現繞道的檔案）、`ChainedScenarioInput.stop` 恢復反序（搬移時漏掉）、
明確傳入不存在的 fixture 仍回 400。
