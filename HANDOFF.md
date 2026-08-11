# HANDOFF — 交接給下一個對話

> 讀完這份就能接手，不需要前文脈絡。
> 最後更新：2026-08-11 · 分支 `refactor/react-agent` · M4 進行中（#01、#02 已結）

---

## 0. 三十秒版本

`/Users/jyp/dev/misty-embodied-agent` 是 Misty II 社交機器人上的 LLM 具身 agent，正在從課堂專案重構成履歷作品。

**先讀 [`PLAN.md`](PLAN.md)** —— 那是完整規格與決策紀錄，本文件只補「現在走到哪、接下來做什麼、有哪些坑」。

進度：**M0–M3 完成；M4（replay harness）進行中，ticket 已結 #01、#02，下一張是 #04**。M0–M10 的定義在 `PLAN.md` §7。

```bash
cd /Users/jyp/dev/misty-embodied-agent
.venv/bin/python -m pytest tests/ -q     # 105 passed
.venv/bin/python test_sim.py             # 24 passed
```

⚠️ **一律用 `.venv`，不要用裸的 `python3`**（`AGENTS.md` 有完整說明）。這台機器的 `python3` 是另一套 miniforge 3.10，沒有 mediapipe 也沒有 opencv，而感知測試在那個環境是 **skip 而不是 fail**——直譯器挑錯了會看起來一片綠。判斷方法是看 skip 數：加 `-rs` 跑，`.venv` 底下 `tests/` 不該有任何一項 skip。

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
| M3 | `65889ff` | 驅動層重寫、刪 `CUBS_Misty.py`、**repo 全面 Apache-2.0**（`PLAN.md` §11） |
| M4 #01 | `a748579` | 鎖定 `mediapipe==0.10.21`，證明感知堆疊真的裝得起來；建 `.venv` |
| M4 #02 | `96f494b` | 臉部偵測抽進 `misty_agent/perception/face.py`，不再需要 import 主腳本 |

⚠️ **2026-08-11 起改為「重寫」而非「修補」，`PLAN.md` §12 是必讀。** 兩個原本的前提被實測推翻：
MediaPipe 的跨幀追蹤**不是**缺陷（真實軌跡下誤差 0.8%，且比關掉它更準更快），
而缺陷 A1 賴以成立的「MediaPipe 每幀 30–50ms」實測是 **3.81ms**——consumer 比 producer 快十倍，
在這台機器上佇列不會積。原 M5（修缺陷 A）與 M6（修控制層）已合併為 **M5：重寫感知→控制管線**。

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
├── perception/
│   ├── asr.py                 # Transcriber port + OpenAI adapter
│   └── face.py                # M4 #02：吃一張影像 → 有沒有人 / 距離 / 是否正在看
└── fakes/fake_robot.py        # RecordingCommands：契約測試 + mock mode 共用
tests/{test_config,test_step_policy,test_drivers_contract,
       test_perception_face,test_perception_stack}.py
full_robot_v3.py               # 主程式，M5–M8 會被拆進 misty_agent/
test_sim.py / test_llm_live.py # 待 M7 遷 pytest
legacy/                        # 舊素材，已從版控移除（.gitignore）
```

---

## 3. 下一步：M4 的 #04（合成影格來源）

**目標**：做一台假相機 + 一份真值軌跡，量出距離讀數落後現實幾秒。規格在
`PLAN.md` §6，**但任務已於 §12.4 改變**，兩者要一起讀。

**任務改了**：原本是「證明舊 code 壞了，測試必須是紅的」。專案已改為重寫而非修補，
所以 harness 變成「量出這台機器的真實數字，據此訂新管線的上界」。**不再需要刻意為紅。**

**已結的兩張**：

- **#01**（`a748579`）`requirements.txt` 的 `mediapipe>=0.10` 會裝到 1.0.0，那裡 legacy `mp.solutions` API 已被上游移除，感知層第一行就 `AttributeError`。改成 `mediapipe==0.10.21`，**那個上限是承重的，不要放寬**。同一張 ticket 建了 `.venv`（見 §4）。
- **#02**（`96f494b`）臉部偵測搬進 `misty_agent/perception/face.py`。介面只認影像，不碰緩衝、執行緒與時間戳。

**#03 已作廢**（`PLAN.md` §12.4）。它要求「原封搬移缺陷，一個都不准修」，目的是留證據
給碼錶量；改成重寫之後沒有要證明的舊缺陷了。

**下一張是 #04**：實作一個滿足 `VideoSource` 的合成影格來源——你說「人在 120 公分」，
它產生一張臉剛好是那個大小的照片。可行性已先驗證：真值 120 / 90 / 60cm 合成後系統
讀回 120.5 / 90.4 / 60.3cm。

M3 已經把地基鋪好：

- `VideoSource` 是 Protocol，harness 只要實作 `start/stop/read/flush/backlog` 就能替換掉
  `RtspVideoStream`，上層一行不動。**這是 M4 的唯一注入點。**
- `CapturedFrame.captured_at` 在 `cap.read()` 回來的瞬間打上（`time.monotonic()`）。
- `backlog` 已在介面上，佇列深度可以直接讀。

**影格來源**：真實人臉照片按已知比例縮放貼上。**純色塊與手繪臉 MediaPipe 都偵測不到**
——這已由 #01 的測試證實，不是推測。fixture 在 72–130cm 範圍內誤差 <1.2%（`PLAN.md` §12.5）。

---

## 4. 坑與已知狀態

### 一定要知道的

- **`git commit` 送的是整個索引**，不是你剛 `git add` 的東西。M0 第一次 commit 就因為索引裡有先前 staged 的刪除，把 34,837 行刪除混進一支「新增 PLAN.md」的 commit。**每次 commit 前先 `git diff --cached --stat` 確認。**
- **`architecture.svg` 有一筆使用者在重構開始前就存在的未提交修改。** 一路刻意排除在所有 commit 之外（`git add -A -- . ':!architecture.svg'`）。不要順手 commit 它。
- **備份在 `~/dev/misty-embodied-agent.backup`**（含原始 `HANDOFF.md`）。`main` 分支未動。

### 環境

- **`.venv` 是 Python 3.11.3**，相依都裝好了（M4 #01 建的），與 `PLAN.md` 定的 Docker 目標版本一致。裸的 `python3` 是另一套 miniforge 3.10，見 §0 的警告。
- `.venv` 不見時：`python3.11 -m venv .venv && .venv/bin/python -m pip install --only-binary=:all: -r requirements.txt`。**一次只跑一個 pip**——兩個 pip 同時對同一個 venv 動作會無聲互鎖。
- `claude` CLI **不在這台機器上**（`which` 的輸出會誤導）。mattpocock skills 是手動複製到 `~/.claude/skills/` 的（29 個）。**skills 只在 session 啟動時掃描。**

### 刻意沒修的（不要以為是漏掉）

- `full_robot_v3.py` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派的 Middle Man。M5–M8 拆檔時整個消失，現在改是做兩次工。
- `config.py` 六個控制律欄位的 Data Clumps（`ApproachPolicy` 子模型想被生出來）→ M5。
- **`AudioStream` 的轉錄跑在 VAD 同一條 thread 上**，網路慢時解碼音訊會堆在後面。與 A 同類（延遲），但不在 harness 的量測範圍內，等 M5 一起看。

### M3 之後的新事實

- **mock mode 現在要顯式開**：`MISTY_MOCK=1`。以前是「import 失敗就靜靜變假機器人」，設定打錯會被吃掉。
- **`cv2` / `av` / `websocket` / `openai` / `mediapipe` 現在都在 `.venv` 裡**（mediapipe 0.10.21、opencv 4.11、av 18、openai 2.53、numpy 1.26）——M3 當時的事實是反過來的，M4 #01 之後才變成這樣。但**當初推導出來的規矩仍然成立**：驅動層刻意把這些 import 移進 adapter 內部，模組本身與契約測試在裸環境下 import 得起來。**寫新驅動碼時保持這個性質。**
- `test_sim.py` 不再 stub `requests`——`robot_commands.py` 在 import 時就從它取名字。

---

## 5. 五個已確認缺陷的現況

完整分析在 `PLAN.md` §5。

| | 缺陷 | 狀態 |
|---|---|---|
| **A** | 閉環實際是開環：queue 無界積壓 + 時間戳蓋錯位置 + 移動後沒作廢舊樣本 | **A1 的前提已被實測推翻**（`PLAN.md` §12.2）：MediaPipe 是 3.81ms 不是 30–50ms，這台機器上佇列不會積。缺陷仍在（管線沒有背壓），但要改成量「翻轉點」。A2/A3 是邏輯錯，不受影響。M4 量 → M5 重寫 |
| **B** | 安全底線 clamp 的是**命令距離**而非**實際行走距離** | 未修（**M5**，已與原 M6 合併）。⚠️ 見下 |
| **C** | `min_step_cm` 下限是死碼兼未爆彈，且**後退方向完全沒有 clamp** | 未修（**M5**）。已有可執行證明 |
| **D** | 動作回傳值被丟棄 | 重寫後自動消失（工具層本來就回傳結構化結果） |
| **E** | 樣本不足時第一輪就 `lost_user`，零重試 | 未修（**M5**） |

**缺陷 B 的措辭要小心。** M2 加的 validator（`target − tolerance > min_safe`）讓那個 runtime guard 對**任何合法 config** 都不可達——這是設計選擇的結果，不是「原分析算錯」。但 validator **完全沒解決** B 的實質：校準誤差為 2 倍時，機器人照樣衝過 45cm。那才是 M5 要做的。

**缺陷 C 仍是真的未爆彈**，且有三種喚醒方式（`tests/test_step_policy.py` 已參數化驗證）：`distance_tolerance_cm=11`、`approach_gain=0.5`、`min_step_cm=10`。

---

## 6. 工作方式（使用者確認過的）

- **每個里程碑 commit 一次**，訊息寫清楚做了什麼與為什麼。commit 前先 `git diff --cached --stat`。
- **偏離計畫要記回 `PLAN.md`**，不要默默改。M1（requirements 只瘦身一半）、M2（缺陷 B 的推論被推翻）、M2.5（review 修正）、M3（三處偏離 + 五個新發現的缺陷）都有留紀錄。
- **先量再定**：門檻與上界一律從實測推導，不憑感覺挑。（原本的「測試先紅」規矩隨著改成重寫而失效，見 `PLAN.md` §12.4。）
- **推翻既有結論要用量的**：M4 期間兩個寫在 `PLAN.md` 裡的前提被實測推翻，都是量出來的，不是想出來的。
- 使用者會直接挑戰建議，且挑戰常常是對的（M2 的「沒機器人量這個有意義嗎」、M3 的「砍掉 AutoMisty」都是使用者提的）。

---

## 7. 建議下一個對話的開場

```
讀 PLAN.md（特別是 §12）與 HANDOFF.md，然後接 M4 的 #04
```

**另外建議找個時間跑一次內建的 code review** —— 到目前為止只跑過 Standards + Spec 兩軸，**正確性軸（失敗情境、崩潰、邏輯錯誤）從未跑過**（`PLAN.md` §10 末段）。M3 新增了約 900 行含 thread 與 socket 的程式碼，是這一軸投報率最高的時候：

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
| `codebase-design` | M3 已用過（deep modules / small interfaces）；M5 重寫管線時再用 |
| `code-review` | 每個里程碑後（Standards + Spec 兩軸） |
| `grill-me` | 遇到新的分歧決策時 |
