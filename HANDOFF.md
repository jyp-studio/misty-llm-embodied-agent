# HANDOFF — 交接給下一個對話

> 讀完這份就能接手，不需要前文脈絡。
> 最後更新：2026-08-20 · 分支 `refactor/react-agent` · **M5 完成，M6 已定案待實作**

---

## 0. 三十秒版本

`/Users/jyp/dev/misty-embodied-agent` 是 Misty II 社交機器人上的 LLM 具身 agent，正在從課堂專案重構成履歷作品。

**先讀 [`PLAN.md`](PLAN.md)** —— 那是完整規格與決策紀錄，本文件只補「現在走到哪、接下來做什麼、有哪些坑」。

進度：**M0–M5 完成。下一站 M6：測試套件收斂。** M0–M10 的定義在 `PLAN.md` §7；
M6/M7 已於 2026-08-20 重整，見 `PLAN.md` §14。詞彙表在 `CONTEXT.md`。

```bash
cd /Users/jyp/dev/misty-embodied-agent
.venv/bin/python -m pytest tests/ -q -rs # 必須零 skip
.venv/bin/python -m harness              # 產出 M5 approach 證據報告
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
| M5 #01 | `dc785ca` | latest-value production distance pipeline + 可判定 freshness 的讀數 |
| M5 #02 | `e773f73` | public bounded `approach()` + post-move fresh readings |
| M5 #03 | 本次提交 | 2× 條件式安全、對稱 bounded step、public-approach sweep、M5 證據 |

**M4 歷史基準**（pre-rewrite，不要當成 M5 現況）：

| | |
|---|---|
| 讀數延遲 p95 | **43ms**，物理下限 38ms（影格週期 33 + 偵測 5），比值 1.11 |
| 佇列翻轉點 | 約 270fps——消費者慢 6 倍以上才會開始積 |
| 舊控制律魯棒邊界 | 1× 完美驅動下收斂到 **1.55s**；1.60s 超衝；1.75s 撞線 |

**M5 正式證據**（`docs/measurements/m5-approach-report.md`）：

| | |
|---|---|
| Production 距離管線延遲 | 三次 replay p95 **43ms**；最嚴格 2× floor bound **74ms，PASS** |
| 新 robustness 邊界 | configured 2× 實際移動倍率下收斂至 **0.65s**；**0.70s** 起 safety-floor breach |
| 2× 舊反例 | 100cm 起步經 public `approach()` 不再低於 45cm，並抵達 band |
| 證據邊界 | 2× 是 UNCALIBRATED、單調最大瞬間位移假設；sweep 不是 sensor measurement；從未跑真機 |

⚠️ **2026-08-11 起改為「重寫」而非「修補」，`PLAN.md` §12 是必讀。** 兩個原本的前提被實測推翻：
MediaPipe 的跨幀追蹤**不是**缺陷（真實軌跡下誤差 0.8%，且比關掉它更準更快），
而缺陷 A1 賴以成立的「MediaPipe 每幀 30–50ms」實測是 **3.81ms**——consumer 比 producer 快十倍，
在這台機器上佇列不會積。原 M5（修缺陷 A）與 M6（修控制層）已合併為 **M5：重寫感知→控制管線**。

**現在的樹**：

```
misty_agent/
├── config.py                  # 全部可調參數；2× motion bound 明列 UNCALIBRATED
├── control/
│   ├── step_policy.py         # plan_step()：控制律的唯一實作
│   └── approach.py            # public bounded closed loop + structured result
├── drivers/
│   ├── robot_commands.py      # Misty 官方 SDK (Apache-2.0)，保留
│   ├── av_stream.py           # AvSession + RtspVideoStream（擷取時打時間戳）
│   ├── audio_stream.py        # AudioStream + UtteranceDetector（純狀態機）
│   └── events.py              # EventStream（websocket）
├── perception/
│   ├── asr.py                 # Transcriber port + OpenAI adapter
│   ├── distance.py            # latest-value production pipeline + timestamps
│   └── face.py                # 吃一張影像 → 有沒有人 / 距離 / 是否正在看
└── fakes/fake_robot.py        # RecordingCommands：契約測試 + mock mode 共用
harness/                       # M4：量測台
├── synthetic_camera.py        # 假相機（VideoSource 的第二個 adapter）
├── trajectory.py              # 劇本：距離對時間的純函式
├── replay.py                  # 錄製 + DistancePipeline（被測物是參數）
├── latency.py                 # 延遲估計（反演 + 互相關）與上界
├── diagnostics.py             # 緩衝深度、幀齡（診斷，不掛門檻）
├── robustness.py              # fake world 經 public approach() 掃 transport lag
├── report.py                  # 組報告（純函式）
└── __main__.py                # python -m harness
docs/measurements/             # M4 歷史基準 + M5 正式證據，產物納入版控
tests/                         # fixtures/ 有兩張人臉 + PROVENANCE；.venv 下零 skip
full_robot_v3.py               # 唯讀參考，不再執行（PLAN.md §12.3）
test_llm_live.py               # M7 加 marker 與斷言，改斷言 Journal 不變量
legacy/                        # 舊素材，已從版控移除（.gitignore）
```

---

## 3. 下一步：M6 測試套件收斂

M5 已把 ReAct 最需要的 deterministic backend 做完：未來 LLM 只需呼叫 public
`approach()`，取得結構化結果，不碰 velocity、`timeMs`、freshness epoch 或控制參數。

⚠️ **M6 的內容在 2026-08-20 換掉了。** 事件流（現稱 **Journal**）已移入 M7，因為它唯一
真實的生產者是 `react.py`。完整理由在 `PLAN.md` §14.1。

M6 的範圍是三件事，spec 在 `.scratch/m6-test-suite-consolidation/spec.md`：

1. ~~覆蓋盤點~~ ✅ `a5c0ca4` + `ac22bbb` → `docs/measurements/m6-coverage-audit.md`
2. ~~刪掉整個舊 runner~~ ✅ 本次提交（不遷移；T8/T9 測的是 M7 會用 function calling 取代的東西）
3. 距離相依的噪音 Sweep —— 參數是 δ_px 不是公分，二維掃 lag × δ_px，只報告邊界曲線

盤點過程另外挖出兩張票：**06**（移動之後才失去使用者，零覆蓋）與 **07**（把盤點裡兩處
論證換成直接斷言）。**frontier 現在是 03、04、06、07 四張，可平行。**

**M6 不開始 Journal、tool registry、LLM orchestration、Audio 或 Docker。**

順序是 spec 的一部分：**盤點先於刪除，刪除先於新測試**，這樣 git 歷史本身就證明覆蓋主張
不是事後補的。下一步是 `/to-tickets`。

`full_robot_v3.py` 繼續是**唯讀參考**，M6 只刪它的測試不刪它本身。LLM prompt 與 memory
folding 等 M7 搬出後再刪。

```bash
.venv/bin/python -m harness              # 重產 docs/measurements/m5-approach-report.md
.venv/bin/python -m pytest tests/ -q -rs # 必須零 skip
```

---

## 4. 坑與已知狀態

### 一定要知道的

- **`git commit` 送的是整個索引**，不是你剛 `git add` 的東西。M0 第一次 commit 就因為索引裡有先前 staged 的刪除，把 34,837 行刪除混進一支「新增 PLAN.md」的 commit。**每次 commit 前先 `git diff --cached --stat` 確認。**
- 工作樹有四筆不屬於 M5 #03 的既有修改：`.env.example`、`architecture.svg`、
  `docs/measurements/m4-harness-report.md`、`tests/conftest.py`。全部保留，提交時用明確檔案清單
  stage；不要用 `git add -A`。
- **備份在 `~/dev/misty-embodied-agent.backup`**（含原始 `HANDOFF.md`）。`main` 分支未動。

### 環境

- **`.venv` 是 Python 3.11.3**，相依都裝好了（M4 #01 建的），與 `PLAN.md` 定的 Docker 目標版本一致。裸的 `python3` 是另一套 miniforge 3.10，見 §0 的警告。
- `.venv` 不見時：`python3.11 -m venv .venv && .venv/bin/python -m pip install --only-binary=:all: -r requirements.txt`。**一次只跑一個 pip**——兩個 pip 同時對同一個 venv 動作會無聲互鎖。
- `claude` CLI **不在這台機器上**（`which` 的輸出會誤導）。mattpocock skills 是手動複製到 `~/.claude/skills/` 的（29 個）。**skills 只在 session 啟動時掃描。**

### 刻意沒修的（不要以為是漏掉）

- `full_robot_v3.py` 的 alias 區塊（`ROBOT_IP = settings.robot_ip` …）是純委派的 Middle Man。
  它會在 M7 搬完 prompt / memory 並刪除舊主腳本時整個消失，現在改是做兩次工。
- `config.py` 的控制欄位仍是一組 Data Clump。M5 刻意保留 frozen `Settings` 作 config 入口，
  只用 `StepPolicyConfig` protocol 縮窄依賴；`PLAN.md` §13.3 已記錄這個決定。
- **`AudioStream` 的轉錄跑在 VAD 同一條 thread 上**，網路慢時解碼音訊會堆在後面。與 A 同類（延遲），但不在 visual harness 或 M5 範圍；等 M7 語音工具前另開 ticket。

### M4 學到的（會再咬人的那種）

- **量測設定必須等於生產設定。這件事咬了兩次。** §12.1 是用病態輸入（一幀之內臉寬跳兩倍）量出 49% 誤差，真實軌跡下只有 0.8%；§12.5 是用「每個距離一個全新偵測器」量的，而 harness 餵的是連續序列，兩者差一個數量級。**兩次數字都是真的，錯的是量的方式。**
- **粗網格會指錯結論，不只是不精確。** #08 的第一版從 1.5 跳到 2.0 秒，跳過了超衝帶，於是把後面的碰撞當成第一個失敗回報——而超衝正是 spec 點名問的三種模式之一。
- **兩個 review agent 不能同時在同一個工作樹上做 mutation testing。** M6 #06 的兩軸 review
  平行跑時互相看到對方注入的缺陷，其中一軸自己開了隔離 worktree 才拿到乾淨結果。要嘛
  各自開 worktree，要嘛序列跑。與使用者在 M6 #03 前撞到的「並行 ticket session 互相讀到
  中間狀態」是同一個形狀。
- **量測設定必須等於生產設定——第三次了。** M6 #03 的交叉檢查用孤立影格餵偵測器，180cm 找不到臉；
  跳著餵改成 120cm 失敗；連續行走則整段零漏偵測。`FaceDetector` 開著跨幀追蹤。見 `PLAN.md` §14.7。
- **診斷器沒看過它要偵測的東西 = 沒有診斷器。** #07 的參考管線佇列永遠是 0，所以另外做了「故意拖慢消費者」的實驗，50ms 那格重現了無限成長與 734ms 幀齡。
- **單次執行的產物不能當結果發布。** #09 的第一版 commit 了一份重跑不出來的報告，而且與它自己指向的文件矛盾。現在跑三次並顯示範圍。
- **打勾時不要順手改驗收條件。** #10 的第一版把 ticket 原文的理由刪掉換成自己的說法再打勾——等於自己改考題。註記要放在原文後面。

### M3 之後的新事實

- **mock mode 現在要顯式開**：`MISTY_MOCK=1`。以前是「import 失敗就靜靜變假機器人」，設定打錯會被吃掉。
- **`cv2` / `av` / `websocket` / `openai` / `mediapipe` 現在都在 `.venv` 裡**（mediapipe 0.10.21、opencv 4.11、av 18、openai 2.53、numpy 1.26）——M3 當時的事實是反過來的，M4 #01 之後才變成這樣。但**當初推導出來的規矩仍然成立**：驅動層刻意把這些 import 移進 adapter 內部，模組本身與契約測試在裸環境下 import 得起來。**寫新驅動碼時保持這個性質。**
- **`requests` 不能被 stub 掉**——`robot_commands.py` 在 import 時就從它取名字。舊 runner 曾經
  stub 它，M3 之後不行了；寫任何會 stub 第三方模組的測試前先確認這件事。

---

## 5. 五個已確認缺陷的現況

完整分析在 `PLAN.md` §5。

| | 缺陷 | 狀態 |
|---|---|---|
| **A** | 閉環實際是開環 | **M5 已修。** latest-value buffer、process-ingress freshness、每次移動後 epoch + 至少兩筆新樣本 |
| **B** | 安全底線 clamp 的是**命令距離**而非**實際行走距離** | **M5 條件式修復。** configured 2× 最大單調位移內不越線；超界與真機仍未知 |
| **C** | `min_step_cm` 下限是死碼兼未爆彈，且**後退方向完全沒有 clamp** | **M5 已修。** min step 是偏好；兩方向共享 arrival-band cap |
| **D** | 動作回傳值被丟棄 | Backend 已修：public `ApproachResult` 結構化回傳；M7 接進 ReAct observation |
| **E** | 樣本不足時第一輪就 `lost_user`，零重試 | **M5 已修。** 在 reading timeout 內輪詢，整次 call 另有 deadline |

**缺陷 B 的措辭要小心。** M2 的 validator 仍讓舊 runtime guard 對任何合法 config 不可達；
M5 不是讓它復活，而是用 `max_actual_motion_multiplier` 對實際位移預留 headroom。這個
guarantee 只存在於明示的模擬前提，不能寫成「真機安全」。

**缺陷 C 的三種喚醒方式仍有回歸測試**，但現在只會讓 min-step preference 生效；最後命令
仍受兩方向共同的 arrival-band cap 約束，不會把已知缺陷叫回來。

---

## 6. 工作方式（使用者確認過的）

- **每個里程碑 commit 一次**，訊息寫清楚做了什麼與為什麼。commit 前先 `git diff --cached --stat`。
- **偏離計畫要記回 `PLAN.md`**，不要默默改。M5 的四 status + truth audit、未建立
  `ApproachPolicy` 子模型、另存 M5 report 都記在 §13.3。
- **先量再定 + public seam TDD**：效能門檻從量測推導；行為修正先由公開介面的失敗測試重現。M5 #03 兩者都有做。
- **推翻既有結論要用量的**：M4 期間兩個寫在 `PLAN.md` 裡的前提被實測推翻，都是量出來的，不是想出來的。
- 使用者會直接挑戰建議，且挑戰常常是對的（M2 的「沒機器人量這個有意義嗎」、M3 的「砍掉 AutoMisty」都是使用者提的）。

---

## 7. 建議下一個對話的開場

```
讀 PLAN.md（特別是 §4、§7、§13）與 HANDOFF.md，grill M6 event stream 的邊界
```

M5 各 ticket 已跑 Standards + Spec 雙軸 review。較廣的**正確性軸**（失敗情境、崩潰、
thread/socket 邏輯）仍可在進 M7 前另做一次，不與 ticket review 混為一談。

```bash
/code-review
```

### 可用的 skills

`~/.agents/skills/` 中與下一步最相關的：

| skill | 何時用 |
|---|---|
| `grill-with-docs` | 對照 PLAN/HANDOFF 壓 M6 的 schema 與 scope |
| `to-spec` / `to-tickets` | grill 後把 M6 定案並拆票 |
| `tdd` / `implement` | 逐 ticket 由 event-stream public behavior 開始 |
| `codebase-design` | 決定 EventBus seam 與 subscriber 邊界 |
| `code-review` | 每個里程碑後（Standards + Spec 兩軸） |
