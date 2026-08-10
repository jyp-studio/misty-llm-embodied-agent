# M4 — Replay harness:證明感知延遲缺陷

Status: ready-for-agent

> 上游脈絡:`PLAN.md` §5(缺陷 A)、§6(測試策略)、§7(里程碑 M4)、§11(M3 結果)。

---

## Problem Statement

這個專案最站得住腳的設計主張是:**LLM 決定「要不要接近」,控制層決定「這一步走幾公分」**——
用確定性閉環取代「LLM 自己算速度 × 時間」的開環做法。README 的開頭就在批判後者。

問題是:**那個閉環目前實際上是開環,而且沒有任何證據可以說明這件事,連否證都做不到。**

距離讀數在送進控制律之前已經過期,原因有三(`PLAN.md` §5):

- **A1** 影格緩衝無界。producer 每幀只 sleep 10ms,consumer 每幀要跑 MediaPipe(30–50ms)
  → 積壓與記憶體單調成長,控制器看到的是幾秒前的畫面。
- **A2** 時間戳蓋在「處理當下」而非「擷取當下」。`get_distance(max_age_sec=2.0)` 的
  age filter **在檢查錯的東西**:它保證「2 秒內算出來」,不保證「2 秒內拍的」。
- **A3** 移動後沒有作廢舊樣本。中位數濾波的視窗會被移動前的樣本主導,
  等於機器人走了一步之後仍用走之前的距離做決策。

更糟的是**現有測試讓這件事看起來是好的**。`test_sim.py` 的 `FakePerception.get_distance()`
直接回傳世界的瞬時真值加雜訊——零延遲、零積壓。它把要測的東西假設掉了,然後 24 個
案例全綠。一個讀 repo 的人會合理地認為閉環已經驗證過。

沒有硬體,而且永久不會有(`PLAN.md` §1)。所以「量一次就知道」這條路是關著的——
除非先造一個能在純軟體裡精確重現這條路徑的東西。

## Solution

一個**重放測試台**:用程式合成一連串影格,每一幀的真值距離精確已知,餵進**真實的**
感知路徑(真的 MediaPipe、真的緩衝、真的中位數濾波),然後量 `get_distance()` 的讀數
落後真值幾秒。

關鍵在於「真實」:合成的是**輸入**,不是**過程**。純色塊 MediaPipe 偵測不到,繞過
MediaPipe 則把主因假設掉——那正是 `test_sim.py` 犯的錯。做法是拿 CC0 授權的人臉圖,
按已知比例縮放後貼到畫布上:MediaPipe 真的偵測得到(耗時真實發生)、真值距離精確
已知、完全可重現、零外部素材相依。

**這個 harness 在 M5 修復之前必須是紅的。** 先證明缺陷存在,再修。反過來做等於沒證明。

一份工作交付四件事(`PLAN.md` §6):可跑的 demo、缺陷 A 的證明、ReAct observation 的
來源、CI 能跑的東西。

### 可量測與不可量測的分界

```
[真值] ─ 相機曝光 → Misty 編碼 → RTSP over WiFi ─▶ [進 process] ─ 緩衝/MediaPipe/濾波 ─▶ [get_distance()]
        └────────── 截段 A:需要硬體,量不到 ──────┘  └──────── 截段 B:100% 在 Python 裡 ────────┘
```

**A1/A2/A3 全部落在截段 B。** harness 注入影格的位置,正是 RTSP 交付影格的位置。
截段 A 以 `sensor_transport_lag_s` 這個標註為 UNCALIBRATED 的參數表示,並用它做
**參數掃描,畫出控制律對其誤差的魯棒邊界**——這比單一數字更有說服力,而且是無硬體
條件下能做出的最強結果。

## User Stories

1. 身為**開發者**,我想要一條可執行的量測,告訴我 `get_distance()` 落後真值幾秒,這樣我才知道缺陷 A 的規模,而不是只有一段推論。
2. 身為**開發者**,我想要這條量測在 M5 修復前是紅的,這樣「修好了」才是一個有意義的斷言。
3. 身為**開發者**,我想要修復前後的對照表(p50 / p95 延遲、緩衝深度上界),這樣我能證明修的是這個缺陷,而不是碰巧變綠。
4. 身為**開發者**,我想要真值距離由建構方式精確已知而非另行估計,這樣量測誤差不會混進被量的對象裡。
5. 身為**開發者**,我想要 MediaPipe 真的在路徑上執行,這樣它 30–50ms 的耗時是真實發生的,而不是被假設掉的。
6. 身為**開發者**,我想要 harness 只透過 `VideoSource` 這一個既有 seam 注入,這樣被測的鏈路和正式執行時是同一條。
7. 身為**開發者**,我想要診斷指標(緩衝深度上界、幀齡 p95)分開呈現且**不掛門檻**,這樣它們能說明現象,而不會變成脆弱的測試。
8. 身為**開發者**,我想要延遲門檻「先量再定」,這樣門檻來自實測而非猜測。
9. 身為**開發者**,我想要用 `sensor_transport_lag_s` 做參數掃描,這樣我能畫出控制律的魯棒邊界,而不是只給一個無法驗證的單點數字。
10. 身為**開發者**,我想要感知的距離估計路徑住在套件裡而非主腳本裡,這樣 harness 不必為了 import 它而 stub 掉 LLM 那一整套。
11. 身為**開發者**,我想要這次抽出是純搬移,這樣缺陷 A 不會在 M4 意外被修掉、害 harness 提早變綠。
12. 身為**履歷讀者**,我想看到專案自己找出並量化了核心缺陷,這樣我知道作者能評估自己的系統,而不只是能寫出系統。
13. 身為**履歷讀者**,我想看到「已模擬驗證」與「未實機驗證」被清楚分開,這樣我知道哪些數字可信。
14. 身為**履歷讀者**,我想要 harness 一行指令就能跑出圖表或數字,這樣我不必架環境就能看到結果。
15. 身為**接手的 agent**,我想要 harness 的斷言描述外部行為而非內部狀態,這樣 M5 重寫內部實作時測試不會整批變紅。
16. 身為**接手的 agent**,我想要合成影格的產生是確定性的(固定 seed / 固定素材),這樣紅綠變化來自程式碼而非隨機。
17. 身為**接手的 agent**,我想知道 M5 要動的是 `VideoSource` 後面而非呼叫端,這樣修法的位置是明確的。
18. 身為**有實機的下游使用者**,我想要校正參數全部集中且標註 UNCALIBRATED,這樣我知道拿到真機後該量哪些東西。
19. 身為**有實機的下游使用者**,我想知道控制律在校正誤差多大的範圍內仍然收斂,這樣我能判斷粗略校正夠不夠用。
20. 身為 **CI**,我想要 harness 免費、確定性、不呼叫任何 LLM,這樣它可以掛在每個 push 上而不會因為模型心情變紅。
21. 身為 **CI**,我想要 harness 在合理時間內跑完,這樣它不會變成大家跳過的那一步。
22. 身為**任何人執行 `pip install -r requirements.txt` 的人**,我想要裝完就能 import 感知層,這樣我不會撞上一個 upstream 已移除的 API。

## Implementation Decisions

### 前置:mediapipe 版本鎖定(阻擋性)

`requirements.txt` 目前是 `mediapipe>=0.10`。upstream 已從 **0.10.31 起移除 legacy
`solutions` API**(1.0.0 亦然),只保留 Tasks API。而 `HumanDetector` 用的正是
`mp.solutions.face_mesh.FaceMesh`。今天全新安裝會裝到 1.0.0 → `AttributeError` →
**整個感知層開不起來**。本機未安裝 mediapipe,所以這個問題至今沒被觸發。

| 版本 | `mp.solutions.face_mesh` |
|---|---|
| ≤ 0.10.21 | 有 |
| ≥ 0.10.31、1.0.0 | 已移除 |

**決定:pin `mediapipe==0.10.21`。** 0.10.21 提供 cp39–cp312 wheel(含
`manylinux_2_28_x86_64`),所以 M9 的 Python 3.11 Docker 不受影響。

#### 為什麼不趁 M4 直接遷移到 Tasks API

反方意見值得記錄:M4 本來就要把 `HumanDetector` 抽進套件,而那正是要遷移的同一段
程式碼,成本確實重疊——「反正整個都在重構」不是隨口說說。

遷移的真實成本也不只是改 API,它比表面上大:

| | 0.10.21 | 1.0.0 |
|---|---|---|
| wheel 內建臉部模型 | `face_landmark.tflite` + `face_landmark_with_attention.tflite` | **0 個** |
| 取得模型 | 自動 | 自備 `.task` bundle(`create_from_model_path`) |

`face_landmark_with_attention.tflite` 正是 `refine_landmarks=True` 用的那個。
Tasks API 要求自備 ~3MB 的模型檔——納入版控或在 CI 下載——這與 harness「零外部素材、
完全可重現」的設計原則(§6)直接相關。此外還有一個**尚未驗證**的假設:Tasks API 一律
輸出 478 點,landmark 234 / 454 / 1 的拓撲應相同、距離算式不用改;這一點無法從 wheel
內容確認。

**但決定性的理由是順序,不是成本。** M4 的全部價值在於「harness 紅了,而且紅的原因
**只可能是**缺陷 A」。同一個里程碑內換掉臉部偵測後端,就多一個候選解釋,而那個解釋
還帶著上述未驗證的拓撲假設。

因此排序為:**M4 用 0.10.21 抽出並量出基準線 → M5 修缺陷 A、產出 before/after 對照表
→ 之後才遷移 Tasks API。** 到那時 harness 已經是遷移的安全網,換後端造成的任何數字
漂移會立刻現形。反過來做,等於在沒有安全網的情況下換掉被測物。

順帶一提,Tasks API 的 `detect_for_video(image, timestamp_ms)` 要求傳入明確時間戳,
而 M3 的 `CapturedFrame.captured_at` 正好餵得進去——**這才是遷移的真正論據**,
而它要等 M5 把時間戳接上之後才兌現得了。

### 抽出感知層(單一 seam 的前提)

距離估計目前住在主腳本 `full_robot_v3` 裡,而該模組在 import 時會建構 OpenAI client。
harness 若直接 import 它,就得重演 `test_sim` 的 stub 大戰,且被測物會持續與 LLM
程式碼糾纏。

**決定:把臉部偵測與距離估計搬進 `misty_agent.perception`**,對應 `PLAN.md` §2 目標
結構裡的 `perception/face.py`(該檔在 §7 未被指派給任何里程碑,現歸入 M4)。

- `misty_agent.perception.face` —— 臉部偵測與由臉寬推距離。介面接受一張影像,回傳
  「有沒有人 / 距離 / 是否正在看」。不知道緩衝、不知道執行緒、不知道時間。
- `misty_agent.perception.distance` —— 消費一個 `VideoSource`,維護樣本視窗,提供
  中位數濾波後的距離讀數與樣本作廢操作。這是缺陷 A2 與 A3 的所在地。
- `full_robot_v3` 的感知類別改為委派,不再自行持有這段邏輯。

**這次抽出必須是純搬移。** 時間戳仍蓋在處理當下、緩衝仍無界、移動後仍不作廢樣本。
任何一項在 M4 被順手修掉,harness 就會提早變綠,M4 也就白做了。

### Seam

**唯一的 seam 是 `VideoSource`**,M3 已建立的 Protocol(`start / stop / read / flush /
backlog`)。harness 提供第二個 adapter,產生合成的 `CapturedFrame`。

選這個高度的理由:再往上一層就是把整個感知類別假掉,那正是 `FakePerception` 的錯誤;
再往下則要動到 cv2 與 RTSP,那是 M3 契約測試的範圍,且與延遲無關。`VideoSource` 是
**還能把 MediaPipe 的真實成本留在量測路徑上的最高 seam**。

**明確不加時鐘 seam。** MediaPipe 的真實耗時就是被量的現象本身,虛擬化時鐘等於把主因
假設掉。harness 以真實時間執行,代價是跑得比較久,這個代價是必要的。

### 影格來源

CC0 授權的人臉圖,由程式按已知比例縮放後貼到指定尺寸的畫布上。縮放比例與
`focal_length`、`real_face_width_cm` 一起決定該幀對應的真值距離,因此真值來自建構方式,
不需要另行估計。素材納入版控,不從網路取用,確保離線可重現。

### 真值軌跡

軌跡是「距離對時間」的函式,涵蓋控制律會遇到的情況:接近中的單調下降、抵達後的
停滯、以及一次階躍(對應機器人移動後視野瞬變,用來曝露 A3)。軌跡以取樣率轉成影格
序列,注入時依真實時間節奏送出。

### 量測

- **主要斷言**:`get_distance()` 讀數落後真值的秒數,以互相關估計,取 p95。
  **門檻先量再定**——先跑一次量出現況,再訂在「修好後實測值 × 安全係數」。
- **診斷指標(不掛門檻)**:緩衝深度上界、幀齡 p95。用 `VideoSource.backlog`,M3 已把
  它放上介面。
- **參數掃描**:以 `sensor_transport_lag_s` 掃出控制律仍收斂的範圍,輸出魯棒邊界。

### 輸出

harness 產生機器可讀的量測結果(供測試斷言)與人可讀的摘要(供 README 與履歷讀者)。
不呼叫任何 LLM。

## Testing Decisions

### 什麼是好測試(本 repo 的既有立場)

只斷言**通過介面可觀察的行為**,不斷言內部狀態。測試應該能在內部實作重寫後存活——
如果實作一改測試就得改,那它測的是介面之外的東西。M3 的教訓是具體的:控制律曾被
手抄一份到測試裡,真實控制律改變時副本會默默分歧而測試照樣綠(`PLAN.md` §10)。

### 會被測到的模組

- `misty_agent.perception.face` —— 給定一張已知臉寬的影像,回傳的距離符合預期。純函式
  式的輸入輸出,不需要 harness。
- `misty_agent.perception.distance` —— 樣本視窗、中位數濾波、樣本作廢的行為。
- **harness 本身** —— 合成器產生的影格,其真值距離與 MediaPipe 實際量到的臉寬一致。
  這一條是 harness 的自我驗證:如果合成器本身有偏差,後面所有延遲數字都不可信。
- **延遲量測** —— 主要斷言,M5 前為紅。

### 既有可參照的測試風格(prior art)

- `tests/test_drivers_contract.py` —— M3 的契約測試。以 `RecordingCommands` 這個
  記錄式 adapter 斷言外部可觀察的請求,並在檔頭明寫「證明什麼、不證明什麼」。
  harness 的量測應沿用這種「先聲明證據範圍」的寫法。
- `tests/test_step_policy.py` —— 以掃描真實函式取代手推閉式解來做可達性分析。
  參數掃描應沿用同樣的取向:掃真的東西,不要推公式。
- `test_sim.py` —— **反面教材**,且其 `FakePerception` 正是 M4 要取代的那個假設。
  M7 才遷移到 pytest;M4 不動它,但 harness 上線後應在該檔註明其侷限。

### CI

harness 掛在每個 push(`ruff` + `pytest` + `docker build` 那條線上)。免費、確定性、
不呼叫 LLM。真 LLM 測試走 `workflow_dispatch`,不擋 merge。

## Out of Scope

- **修復缺陷 A**——那是 M5。M4 只證明它存在。刻意讓 harness 保持紅色。
- **效能最佳化**——不調 MediaPipe 參數、不換模型、不加速任何東西。這是正確性問題,
  不是效能問題(`PLAN.md` §5 已定調)。
- **遷移到 MediaPipe Tasks API**——另立里程碑。M4 只 pin 版本止血。
- **截段 A(相機到 process)的實際量測**——需要硬體,永久不可得。只以掃描表示。
- **缺陷 B / C / E**——控制層的工作,M6。
- **LLM 決策測試**——M8,需要 ReAct 迴圈先存在。
- **`test_sim.py` 遷移到 pytest**——M7。
- **`full_robot_v3` 的其餘部分搬進套件**——M5–M8 逐步進行。M4 只搬距離估計路徑,
  因為那是 harness 必須觸及的部分。
- **README 改寫**——M10。但 M4 產出的誠實邊界敘述應保留給它使用。

## Further Notes

- **M3 已鋪好的地基**:`CapturedFrame.captured_at` 在影格離開傳輸層的瞬間打上
  (`time.monotonic()`),但**消費端刻意還沒使用**——那是 M5 的修法。M4 期間必須維持
  這個狀態。`VideoSource.backlog` 也已在介面上,診斷指標可直接讀。
- **queue 藏在 `read()` 後面**是 M3 的設計偏離(記於 `PLAN.md` §11):M5 修 A1 只需
  改 `RtspVideoStream` 一處,呼叫端不動。M4 的 harness 因此也不需要模擬 queue 行為,
  它只要餵影格。
- **本機環境**:Python 3.10.6,無 venv,`cv2` / `av` / `websocket` / `openai` /
  `mediapipe` 皆未安裝。M4 是第一個真的需要 `mediapipe` 與 `opencv-python` 的里程碑,
  安裝步驟屬於 M4 的一部分。M3 的驅動層刻意把重相依 import 移進 adapter 內部,讓模組
  在裸環境下 import 得起來——**新增的感知模組應維持這個性質**,否則 `pytest` 會直接掛。
- **M9 的 Docker 提醒**:mediapipe 0.10.21 沒有 `aarch64` 的 manylinux wheel。在 Apple
  Silicon 上建 image 需指定 `--platform linux/amd64`。
- **驗證邊界的措辭**:harness 證明的是**截段 B 的時間語意**,不證明真機上的端到端延遲。
  這條線要和 M3 契約測試那條線(證明請求格式,不證明機器人會照做)一起寫進 README。
- **`architecture.svg` 有一筆重構前就存在的未提交修改**,一路刻意排除在所有 commit
  之外。不要順手 commit 它。
