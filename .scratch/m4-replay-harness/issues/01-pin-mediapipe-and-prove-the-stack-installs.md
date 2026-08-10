# 01 — 鎖定 mediapipe 並證明感知堆疊裝得起來

**What to build:** 一個全新的環境跑完安裝步驟之後,真的 MediaPipe 能在一張人臉圖上
偵測到臉並回報臉寬。今天做不到——宣告的相依會裝出一個開不起來的感知層。

`requirements.txt` 寫的是 `mediapipe>=0.10`,而 upstream 從 **0.10.31** 起移除了
legacy `solutions` API(1.0.0 亦然),只留 Tasks API。臉部偵測用的正是
`mp.solutions.face_mesh`,所以今天全新安裝會裝到 1.0.0 並在建構偵測器的第一行就
`AttributeError`。本機從未安裝 mediapipe,所以這個問題至今沒被觸發。

**這是整個 M4 的阻擋性前置**:harness 必須跑真的 MediaPipe(合成色塊偵測不到,
繞過 MediaPipe 等於把主因假設掉,見 spec)。

版本事實(已用 wheel 內容驗證):

| 版本 | `mp.solutions.face_mesh` | wheel 內建臉部模型 |
|---|---|---|
| ≤ 0.10.21 | 有 | `face_landmark.tflite` + `face_landmark_with_attention.tflite` |
| ≥ 0.10.31、1.0.0 | 已移除 | **0 個**(需自備 `.task` bundle) |

0.10.21 提供 cp39–cp312 wheel,含 `manylinux_2_28_x86_64`,所以 M9 的 Python 3.11
Docker 不受影響。**但沒有 aarch64 的 manylinux wheel** —— M9 在 Apple Silicon 上
建 image 要指定 `--platform linux/amd64`。

遷移到 Tasks API **不在 M4 範圍內**,理由見 spec 的「為什麼不趁 M4 直接遷移」。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `mediapipe` 在相依宣告中鎖到一個仍提供 legacy `solutions` API 的版本,並在原地
      註明為何不能放寬(否則下一個人會「順手升級」再把感知層弄壞一次)
- [ ] `opencv-python` 一併確認可安裝,harness 需要它合成影格
- [ ] 一張 CC0 授權的人臉圖納入版控作為測試 fixture,不從網路取用
- [ ] 一支 smoke test:載入該 fixture、跑真的臉部偵測、斷言有偵測到臉且臉寬像素數
      落在合理範圍。**這是本 repo 第一次真的執行 MediaPipe**
- [ ] 該 smoke test 明確標記,讓沒有安裝重相依的環境能略過而非整批錯誤——驅動層
      模組在裸環境下 import 得起來的性質必須維持(見 `AGENTS.md` 與 M3 的做法)
- [ ] `pytest` 與 `test_sim.py` 兩套仍全綠
