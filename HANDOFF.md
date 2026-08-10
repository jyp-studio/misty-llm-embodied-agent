# HANDOFF — 交接給下一個對話

> 讀完這份就能接手，不需要前文脈絡。
> 最後更新：2026-08-10 · 分支 `refactor/react-agent` · HEAD `2e8f745`

---

## 0. 三十秒版本

`/Users/jyp/dev/misty-embodied-agent` 是 Misty II 社交機器人上的 LLM 具身 agent，正在從課堂專案重構成履歷作品。

**先讀 [`PLAN.md`](PLAN.md)** —— 那是完整規格與決策紀錄，本文件只補「現在走到哪、接下來做什麼、有哪些坑」。

進度：**M0–M2.5 完成，下一步 M3（驅動層重寫）**。M0–M11 的定義在 `PLAN.md` §7。

```bash
cd /Users/jyp/dev/misty-embodied-agent
python3 -m pytest tests/ -q     # 37 passed
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

**現在的樹**（版控中 20 個檔案）：

```
misty_agent/
├── config.py                  # 全部可調參數 + 跨欄位 validator
└── control/step_policy.py     # plan_step()：控制律的唯一實作
tests/{test_config,test_step_policy}.py
full_robot_v3.py               # 主程式，M3–M8 會被拆進 misty_agent/
CUBS_Misty.py                  # ⚠️ AutoMisty 衍生，M3 要重寫
RobotCommands.py               # Misty 官方 SDK (Apache-2.0)，保留
test_sim.py / test_llm_live.py # 待 M7 遷 pytest
legacy/                        # 舊素材，已從版控移除（.gitignore）
```

---

## 3. 下一步：M3 驅動層重寫

**目標**：把 `CUBS_Misty.py` 的 `Robot(RobotCommands)` 換成自己寫的 `misty_agent/drivers/`。

主程式對它的依賴只有 10 個符號（其中 4 個私有，本身就是設計異味）：

```
公開  start_av_stream · stop_av_streaming · frame_queue · transcript_queue · ip
私有  _video_reader_thread · _read_audio_stream · _process_audio · _stop_event
移除  load_whisper_model  ← 改用 API 轉錄（M2 已決定）
另有  register_event      ← websocket，foot-bumper e-stop
```

拆成四件：`drivers/av_stream.py`、`audio_stream.py`、`events.py`、`robot_commands.py`（後者是保留的官方 SDK）。實際重寫約 200–300 行。

**M3 必須連帶做的三件事**（漏了就會留下不一致）：

1. **`av_stream.py` 在擷取影格時就打時間戳並隨幀傳遞** —— 這是缺陷 A2 的地基，M5 修 A 時會用到。
2. **更新 `NOTICE`** —— 目前它明列 `CUBS_Misty.py` 仍受上游 Academic Research License 管轄。刪掉該檔後要改成「已無 AutoMisty 衍生程式碼」，並可刪 `legacy/LICENSE.AutoMisty`。**在此之前 repo 尚未完全 Apache-2.0。**
3. **清掉 `requirements.txt` 的過渡依賴區塊** —— `openai-whisper`（連帶 torch ~800MB）、`langchain-*`、`librosa`、`pynput` 只有 `CUBS_Misty.py` 在用。

**驗證方式**：契約測試——對照 `docs.mistyrobotics.com` 驗證送出的 HTTP/WebSocket 請求格式。**證明請求格式正確，不證明機器人會照做。** 這條線要寫進 README。

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

- `full_robot_v3.py:101-120` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派的 Middle Man。M3–M8 拆檔時整個消失，現在改是做兩次工。
- `CUBS_Misty.py:22,24,25`（`sys.path.append("/Users/xiaowang/...")` 與壞掉的自我 import）。該檔 M3 整個取代，且現在仍受上游授權管轄。
- `config.py` 六個控制律欄位的 Data Clumps（`ApproachPolicy` 子模型想被生出來）→ M6。

---

## 5. 五個已確認缺陷的現況

完整分析在 `PLAN.md` §5。

| | 缺陷 | 狀態 |
|---|---|---|
| **A** | 閉環實際是開環：queue 無界積壓 + 時間戳蓋錯位置 + 移動後沒作廢舊樣本 | 未修。M3 打地基 → M4 建 harness 證明 → M5 修 |
| **B** | 安全底線 clamp 的是**命令距離**而非**實際行走距離** | 未修（M6）。⚠️ 見下 |
| **C** | `min_step_cm` 下限是死碼兼未爆彈，且**後退方向完全沒有 clamp** | 未修（M6）。已有可執行證明 |
| **D** | 動作回傳值被丟棄 | 重寫後自動消失（工具層本來就回傳結構化結果） |
| **E** | 樣本不足時第一輪就 `lost_user`，零重試 | 未修（M6） |

**缺陷 B 的措辭要小心。** M2 加的 validator（`target − tolerance > min_safe`）讓那個 runtime guard 對**任何合法 config** 都不可達——這是設計選擇的結果，不是「原分析算錯」。但 validator **完全沒解決** B 的實質：校準誤差為 2 倍時，機器人照樣衝過 45cm。那才是 M6 要做的。

**缺陷 C 仍是真的未爆彈**，且有三種喚醒方式（`tests/test_step_policy.py` 已參數化驗證）：`distance_tolerance_cm=11`、`approach_gain=0.5`、`min_step_cm=10`。

---

## 6. 工作方式（使用者確認過的）

- **每個里程碑 commit 一次**，訊息寫清楚做了什麼與為什麼。commit 前先 `git diff --cached --stat`。
- **偏離計畫要記回 `PLAN.md`**，不要默默改。M1（requirements 只瘦身一半）、M2（缺陷 B 的推論被推翻）、M2.5（review 修正）都有留紀錄。
- **測試先紅**：M4 的 harness 在修復前必須是紅的，否則等於沒證明缺陷 A 存在。
- 使用者會直接挑戰建議，且挑戰常常是對的（M2 的「沒機器人量這個有意義嗎」、M3 的「砍掉 AutoMisty」都是使用者提的）。

---

## 7. 建議下一個對話的開場

```
讀 PLAN.md 與 HANDOFF.md，然後開始 M3
```

**但在 M3 之前，建議先跑一次內建的 code review** —— M2.5 只跑了 Standards + Spec 兩軸，**正確性軸（失敗情境、崩潰、邏輯錯誤）從未跑過**，而那正是抓出 M2 那個 reachability bug 的同類問題會出現的地方：

```bash
/code-review
```

這是**使用者手動觸發**的，agent 不能代跑。

### 可用的 skills

`~/.claude/skills/` 有 29 個 mattpocock skills。與本專案最相關的：

| skill | 何時用 |
|---|---|
| `codebase-design` | **M3 對症**——deep modules / small interfaces，正是「10 個依賴符號有 4 個是私有的」要解的問題 |
| `tdd` | M4/M5，計畫本來就要求測試先紅 |
| `diagnosing-bugs` | M4/M5 追感知延遲 |
| `code-review` | 每個里程碑後（Standards + Spec 兩軸） |
| `grill-me` | 遇到新的分歧決策時 |
