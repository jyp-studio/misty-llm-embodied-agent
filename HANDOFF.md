# HANDOFF — 交接給下一個對話

> 讀完這份就能接手，不需要前文脈絡。
> 最後更新：2026-08-12 · 分支 `refactor/react-agent` · **M4 完成，下一站 M5**

---

## 0. 三十秒版本

`/Users/jyp/dev/misty-embodied-agent` 是 Misty II 社交機器人上的 LLM 具身 agent，正在從課堂專案重構成履歷作品。

**先讀 [`PLAN.md`](PLAN.md)** —— 那是完整規格與決策紀錄，本文件只補「現在走到哪、接下來做什麼、有哪些坑」。

進度：**M0–M4 完成。下一站 M5：重寫感知→控制管線。** M0–M10 的定義在 `PLAN.md` §7。

```bash
cd /Users/jyp/dev/misty-embodied-agent
.venv/bin/python -m pytest tests/ -q     # 232 passed
.venv/bin/python -m harness              # 跑一次量測，產出報告
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
| M4 #01 | `a748579` | 鎖定 `mediapipe==0.10.21`（repo 先前其實裝不起來）；建 `.venv` |
| M4 #02 | `96f494b` | 臉部偵測抽進 `misty_agent/perception/face.py` |
| — | `fd7cd5a` | **改成重寫而非修補**，撤回兩個被實測推翻的前提（`PLAN.md` §12） |
| M4 #04 | `5576d51` | 合成影格來源，真值由建構方式決定 |
| M4 #05 | `2f05d5c` | 真值軌跡重放，產出 trace |
| M4 #06 | `dc2f005` | 量出延遲並訂出新管線的上界 |
| M4 #07 | `a2b38c3` | 緩衝深度與幀齡診斷，實地演示缺陷 A1 |
| M4 #08 | `2d892df` | 傳輸延遲的魯棒邊界掃描 |
| M4 #09 | `e4b7ad2` | `python -m harness` 一行產出人可讀報告 |
| M4 #10 | `5005462` | 凝視判斷的陰性對照 fixture |

**M4 量到的數字**（`docs/measurements/`，`python -m harness` 可重跑）：

| | |
|---|---|
| 讀數延遲 p95 | **43ms**，物理下限 38ms（影格週期 33 + 偵測 5），比值 1.11 |
| 佇列翻轉點 | 約 270fps——消費者慢 6 倍以上才會開始積 |
| 控制律魯棒邊界 | 收斂到 **1.55s** 假設傳輸延遲；1.60s 超衝；1.75s 撞線 |

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
│   └── face.py                # 吃一張影像 → 有沒有人 / 距離 / 是否正在看
└── fakes/fake_robot.py        # RecordingCommands：契約測試 + mock mode 共用
harness/                       # M4：量測台
├── synthetic_camera.py        # 假相機（VideoSource 的第二個 adapter）
├── trajectory.py              # 劇本：距離對時間的純函式
├── replay.py                  # 錄製 + DistancePipeline（被測物是參數）
├── latency.py                 # 延遲估計（反演 + 互相關）與上界
├── diagnostics.py             # 緩衝深度、幀齡（診斷，不掛門檻）
├── robustness.py              # 傳輸延遲掃描，閉環驅動真實控制律
├── report.py                  # 組報告（純函式）
└── __main__.py                # python -m harness
docs/measurements/             # 三份，產物納入版控供無相依者閱讀
tests/                         # 232 passed；fixtures/ 有兩張人臉 + PROVENANCE
full_robot_v3.py               # 唯讀參考，不再執行（PLAN.md §12.3）
test_sim.py / test_llm_live.py # 待 M6 遷 pytest
legacy/                        # 舊素材，已從版控移除（.gitignore）
```

---

## 3. 下一步：M5 重寫感知→控制管線

**範圍只到感知→控制那條線**（影格 → 距離 → 走幾公分）。ReAct、記憶、事件流不在內——那些不是寫壞了而是還沒寫（`PLAN.md` §12.3）。原 M5（修缺陷 A）與 M6（修控制層）已合併成這一個。

`full_robot_v3.py` 是**唯讀參考**：不再執行、不再維護，只在需要對照舊行為時去讀。它仍是 LLM prompt 與記憶折疊邏輯的唯一記載，等 M7 把該搬的搬完再刪。

### 靶已經很具體，而且可執行

| 要達成的 | 依據 | 怎麼知道有沒有達成 |
|---|---|---|
| 延遲 p95 ≤ 物理下限的 2 倍 | #06 | `tests/test_latency_bound.py`，現在綠的，新管線接上同一把尺 |
| 佇列要有背壓 | #07 | `test_diagnostics.py` 演示過沒有背壓時幀齡衝到 734ms |
| **決策當下限制讀數年齡** | #08 | 見下，這是最重要的一條 |

### #08 的發現：失敗是無聲的

掃描顯示控制器在安全底線內 4 公分處**仍回報 `arrived`**，而且**沒有任何延遲值會讓它察覺**——它判斷「抵達」的依據是拿讀數比對抵達帶，而讀數和其他東西一樣過期。

所以新管線不能只是「讀數變新鮮」，它必須讓**過期的讀數無法被當成決策依據**。`CapturedFrame.captured_at`（M3 就備好了）在這裡才第一次真的被用上。

魯棒邊界 1.55s 也不是控制器聰明，是 `post_step_settle_s = 0.8s` 剛好買到的——把沉澱時間減半讓機器人反應快一點，邊界就跟著減半。

### 接上 harness 的方式

新管線只要滿足 `harness.replay.DistancePipeline`（一個方法：`latest_reading()`），就能用**同一把尺**量，和 `DirectPipeline` 的基準線直接可比。這是刻意的：#03 被作廢後，被測物就設計成參數而不是寫死的。

```python
.venv/bin/python -m harness          # 跑量測，寫 docs/measurements/m4-harness-report.md
.venv/bin/python -m pytest tests/ -q # 232 passed
```

### 缺陷 B/C/E 也在這個里程碑

`PLAN.md` §5 的 B（安全底線 clamp 的是命令距離而非實際距離）、C（後退方向沒有 clamp）、E（樣本不足就放棄）都併進 M5。#08 已經把 B 重現到公分：`speed_error=2.0` 從 100cm 起步，最近距離 44.0cm。

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

### M4 學到的（會再咬人的那種）

- **量測設定必須等於生產設定。這件事咬了兩次。** §12.1 是用病態輸入（一幀之內臉寬跳兩倍）量出 49% 誤差，真實軌跡下只有 0.8%；§12.5 是用「每個距離一個全新偵測器」量的，而 harness 餵的是連續序列，兩者差一個數量級。**兩次數字都是真的，錯的是量的方式。**
- **粗網格會指錯結論，不只是不精確。** #08 的第一版從 1.5 跳到 2.0 秒，跳過了超衝帶，於是把後面的碰撞當成第一個失敗回報——而超衝正是 spec 點名問的三種模式之一。
- **診斷器沒看過它要偵測的東西 = 沒有診斷器。** #07 的參考管線佇列永遠是 0，所以另外做了「故意拖慢消費者」的實驗，50ms 那格重現了無限成長與 734ms 幀齡。
- **單次執行的產物不能當結果發布。** #09 的第一版 commit 了一份重跑不出來的報告，而且與它自己指向的文件矛盾。現在跑三次並顯示範圍。
- **打勾時不要順手改驗收條件。** #10 的第一版把 ticket 原文的理由刪掉換成自己的說法再打勾——等於自己改考題。註記要放在原文後面。

### M3 之後的新事實

- **mock mode 現在要顯式開**：`MISTY_MOCK=1`。以前是「import 失敗就靜靜變假機器人」，設定打錯會被吃掉。
- **`cv2` / `av` / `websocket` / `openai` / `mediapipe` 現在都在 `.venv` 裡**（mediapipe 0.10.21、opencv 4.11、av 18、openai 2.53、numpy 1.26）——M3 當時的事實是反過來的，M4 #01 之後才變成這樣。但**當初推導出來的規矩仍然成立**：驅動層刻意把這些 import 移進 adapter 內部，模組本身與契約測試在裸環境下 import 得起來。**寫新驅動碼時保持這個性質。**
- `test_sim.py` 不再 stub `requests`——`robot_commands.py` 在 import 時就從它取名字。

---

## 5. 五個已確認缺陷的現況

完整分析在 `PLAN.md` §5。

| | 缺陷 | 狀態 |
|---|---|---|
| **A** | 閉環實際是開環 | **M4 已全部量完。** A1：佇列翻轉點約 270fps，這台機器上不會積——但管線**沒有背壓**，#07 故意把消費者拖慢到 50ms 就重現了無限成長與 734ms 幀齡。A2/A3 是邏輯錯，與機器無關。M5 重寫 |
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
讀 PLAN.md（特別是 §12）與 HANDOFF.md，然後開始 M5
```

**另外建議找個時間跑一次內建的 code review** —— 到目前為止只跑過 Standards + Spec 兩軸，**正確性軸（失敗情境、崩潰、邏輯錯誤）從未跑過**（`PLAN.md` §10 末段）。M3 與 M4 加起來新增了約 4000 行，含 thread、socket 與整套量測程式，是這一軸投報率最高的時候：

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
