# HANDOFF — 交接給下一個對話

> 讀完這份就能接手，不需要前文脈絡。
> 最後更新：2026-08-10 · 分支 `refactor/react-agent` · M3 完成

---

## 0. 三十秒版本

`/Users/jyp/dev/misty-embodied-agent` 是 Misty II 社交機器人上的 LLM 具身 agent，正在從課堂專案重構成履歷作品。

**先讀 [`PLAN.md`](PLAN.md)** —— 那是完整規格與決策紀錄，本文件只補「現在走到哪、接下來做什麼、有哪些坑」。

進度：**M0–M3 完成，下一步 M4（replay harness）**。M0–M11 的定義在 `PLAN.md` §7。

```bash
cd /Users/jyp/dev/misty-embodied-agent
python3 -m pytest tests/ -q     # 80 passed
python3 test_sim.py             # 24 passed
```

---

## 1. 硬前提（會決定所有技術選擇）

| | |
|---|---|
| **永久無實機** | 不要提出任何需要碰硬體的方案。`approach_user()` 從未在真機執行過 |
| **交付定位** | 履歷作品（ReAct agent + Docker + CI/CD），不是可上線系統 |
| **誠實標註** | 未經實機驗證的一律標明，清單在 `PLAN.md` §8 |
| **不動 GitHub** | 只改本地。`origin/main` 維持原狀直到 M11 |
| **語言** | 使用者用繁體中文（台灣） |

---

## 2. 已完成

| 里程碑 | commit | 內容 |
|---|---|---|
| M0 | `025ce70` | 備份 + 分支 + `PLAN.md` |
| M1 | `8a8dee8` | 移除 AutoMisty（8512 行）、改 Apache-2.0、`legacy/` 隔離 |
| M2 | `1d5f2ed` | `misty_agent/config.py`，pydantic-settings 收攏全部可調參數 |
| M2.5 | `2e8f745` | 兩軸 code review + 修正（`PLAN.md` §10） |
| M3 | 本次 | 驅動層重寫、刪 `CUBS_Misty.py`、**repo 全面 Apache-2.0**（`PLAN.md` §11） |

**現在的樹**：

```
misty_agent/
├── config.py                  # 全部可調參數 + 跨欄位 validator
├── control/step_policy.py     # plan_step()：控制律的唯一實作
├── drivers/
│   ├── robot_commands.py      # Misty 官方 SDK (Apache-2.0)，保留
│   ├── av_stream.py           # AvSession + RtspVideoStream（擷取時打時間戳）
│   ├── audio_stream.py        # AudioStream + UtteranceDetector（純狀態機）
│   └── events.py              # EventStream（websocket）
├── perception/asr.py          # Transcriber port + OpenAI adapter
└── fakes/fake_robot.py        # RecordingCommands：契約測試 + mock mode 共用
tests/{test_config,test_step_policy,test_drivers_contract}.py
full_robot_v3.py               # 主程式，M5–M8 會被拆進 misty_agent/
test_sim.py / test_llm_live.py # 待 M7 遷 pytest
legacy/                        # 舊素材，已從版控移除（.gitignore）
```

---

## 3. 下一步：M4 replay harness

**目標**：合成影格 + 真值軌跡，量出 `get_distance()` 落後真值多少秒。**此時必須是紅的**——先證明缺陷 A 存在，M5 才有東西可修。完整規格在 `PLAN.md` §6。

M3 已經把地基鋪好：

- `CapturedFrame.captured_at` 在 `cap.read()` 回來的瞬間打上（`time.monotonic()`）。
- **`full_robot_v3.py:290` 刻意還沒用它**——consumer 仍在處理當下打 `time.time()`。這就是缺陷 A2 還活著的地方，M5 才改。
- `VideoSource` 是 Protocol，harness 只要實作 `start/stop/read/flush/backlog` 就能替換掉 `RtspVideoStream`，主程式一行不動。**這是 M4 的注入點。**
- `backlog` 已在介面上，缺陷 A1 的診斷指標可以直接讀。

⚠️ **不要在 M4 順手修 A1/A2。** 先量，紅了，才修（M5）。

**影格來源**：CC0 人臉圖 + 程式按已知比例縮放貼上——MediaPipe 真的偵測得到（耗時真實發生）、真值距離精確已知、零外部素材。純色塊會被 MediaPipe 略過，等於把主因假設掉。

---

## 4. 坑與已知狀態

### 一定要知道的

- **`git commit` 送的是整個索引**，不是你剛 `git add` 的東西。M0 第一次 commit 就因為索引裡有先前 staged 的刪除，把 34,837 行刪除混進一支「新增 PLAN.md」的 commit。**每次 commit 前先 `git diff --cached --stat` 確認。**
- **`architecture.svg` 有一筆使用者在重構開始前就存在的未提交修改。** 一路刻意排除在所有 commit 之外（`git add -A -- . ':!architecture.svg'`）。不要順手 commit 它。
- **備份在 `~/dev/misty-embodied-agent.backup`**（含原始 `HANDOFF.md`）。`main` 分支未動。

### 環境

- 本機 **Python 3.10.6**，但 `PLAN.md` 定 Docker 用 3.11。目前無影響，M9 前若要一致再處理。
- `pydantic-settings` 與 `pytest` 是直接 `pip install` 到使用者全域環境的，**沒有 venv**。M9 前可考慮建一個。
- `claude` CLI **不在這台機器上**（`which` 的輸出會誤導）。mattpocock skills 是手動複製到 `~/.claude/skills/` 的（29 個）。**skills 只在 session 啟動時掃描。**

### 刻意沒修的（不要以為是漏掉）

- `full_robot_v3.py` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派的 Middle Man。M5–M8 拆檔時整個消失，現在改是做兩次工。
- `config.py` 六個控制律欄位的 Data Clumps（`ApproachPolicy` 子模型想被生出來）→ M6。
- **`AudioStream` 的轉錄跑在 VAD 同一條 thread 上**，網路慢時解碼音訊會堆在後面。與 A 同類（延遲），但不在 harness 的量測範圍內，等 M5 一起看。

### M3 之後的新事實

- **mock mode 現在要顯式開**：`MISTY_MOCK=1`。以前是「import 失敗就靜靜變假機器人」，設定打錯會被吃掉。
- **本機沒裝 `cv2` / `av` / `websocket` / `openai` / `mediapipe`**。驅動層因此刻意把這些 import 移進 adapter 內部，模組本身與契約測試在裸環境下 import 得起來。**寫新驅動碼時保持這個性質**，否則 `pytest` 直接掛。
- `test_sim.py` 不再 stub `requests`——`robot_commands.py` 在 import 時就從它取名字。

---

## 5. 五個已確認缺陷的現況

完整分析在 `PLAN.md` §5。

| | 缺陷 | 狀態 |
|---|---|---|
| **A** | 閉環實際是開環：queue 無界積壓 + 時間戳蓋錯位置 + 移動後沒作廢舊樣本 | 未修。**M3 地基已完成**（`CapturedFrame.captured_at`）→ M4 建 harness 證明 → M5 修 |
| **B** | 安全底線 clamp 的是**命令距離**而非**實際行走距離** | 未修（M6）。⚠️ 見下 |
| **C** | `min_step_cm` 下限是死碼兼未爆彈，且**後退方向完全沒有 clamp** | 未修（M6）。已有可執行證明 |
| **D** | 動作回傳值被丟棄 | 重寫後自動消失（工具層本來就回傳結構化結果） |
| **E** | 樣本不足時第一輪就 `lost_user`，零重試 | 未修（M6） |

**缺陷 B 的措辭要小心。** M2 加的 validator（`target − tolerance > min_safe`）讓那個 runtime guard 對**任何合法 config** 都不可達——這是設計選擇的結果，不是「原分析算錯」。但 validator **完全沒解決** B 的實質：校準誤差為 2 倍時，機器人照樣衝過 45cm。那才是 M6 要做的。

**缺陷 C 仍是真的未爆彈**，且有三種喚醒方式（`tests/test_step_policy.py` 已參數化驗證）：`distance_tolerance_cm=11`、`approach_gain=0.5`、`min_step_cm=10`。

---

## 6. 工作方式（使用者確認過的）

- **每個里程碑 commit 一次**，訊息寫清楚做了什麼與為什麼。commit 前先 `git diff --cached --stat`。
- **偏離計畫要記回 `PLAN.md`**，不要默默改。M1（requirements 只瘦身一半）、M2（缺陷 B 的推論被推翻）、M2.5（review 修正）、M3（三處偏離 + 五個新發現的缺陷）都有留紀錄。
- **測試先紅**：M4 的 harness 在修復前必須是紅的，否則等於沒證明缺陷 A 存在。
- 使用者會直接挑戰建議，且挑戰常常是對的（M2 的「沒機器人量這個有意義嗎」、M3 的「砍掉 AutoMisty」都是使用者提的）。

---

## 7. 建議下一個對話的開場

```
讀 PLAN.md 與 HANDOFF.md，然後開始 M4
```

**但在 M4 之前，建議先跑一次內建的 code review** —— 到目前為止只跑過 Standards + Spec 兩軸，**正確性軸（失敗情境、崩潰、邏輯錯誤）從未跑過**。M3 新增了約 900 行含 thread 與 socket 的程式碼，是這一軸投報率最高的時候：

```bash
/code-review
```

這是**使用者手動觸發**的，agent 不能代跑。

### 可用的 skills

`~/.claude/skills/` 有 29 個 mattpocock skills。與本專案最相關的：

| skill | 何時用 |
|---|---|
| `tdd` | **M4/M5 對症**——計畫本來就要求測試先紅 |
| `diagnosing-bugs` | M4/M5 追感知延遲 |
| `codebase-design` | M3 已用過（deep modules / small interfaces）；M6 拆控制層時再用 |
| `code-review` | 每個里程碑後（Standards + Spec 兩軸） |
| `grill-me` | 遇到新的分歧決策時 |
