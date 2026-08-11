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

**Status:** resolved

> 完成於 2026-08-11。量到的數字:fixture 960×1200,MediaPipe 回傳 **478** 個
> landmark,臉頰到臉頰 **184.7px(畫面寬 19.2%)**,依專案公式換算 52.8cm。
> 順帶實證了 `PLAN.md` §6 的前提:**純色塊與手繪臉都偵測不到**——那條前提
> 決定了整個 harness 的設計,但在此之前從未被驗證過。

- [x] `mediapipe` 在相依宣告中鎖到一個仍提供 legacy `solutions` API 的版本,並在原地
      註明為何不能放寬(否則下一個人會「順手升級」再把感知層弄壞一次)
      → 鎖 `0.10.21`,已裝進 `.venv` 並確認 `solutions.face_mesh` 存在
- [x] `opencv-python` 一併確認可安裝,harness 需要它合成影格 → 4.11.0
- [x] 一張 CC0 授權的人臉圖納入版控作為測試 fixture,不從網路取用
      → NASA 官方太空人肖像(公有領域,正面、完整頭部帶邊距),來源與 SHA-256
      記於 fixtures 的 `PROVENANCE.md`。授權由 CC0 放寬為公有領域,理由同記於該檔
- [x] 一支 smoke test:載入該 fixture、跑真的臉部偵測、斷言有偵測到臉且臉寬像素數
      落在合理範圍。**這是本 repo 第一次真的執行 MediaPipe**
      → 期望值由**構圖**推得:頭肩肖像的頭部約佔畫面寬 1/5 到 1/3。接受區間放寬為
      12–45%,理由是這些 landmark 描的是臉部輪廓(比視覺上的頭部外緣窄),且要容忍
      MediaPipe 版本變動。實測 19.2%,略低於構圖預測——正是輪廓比頭窄的表現
- [x] 該 smoke test 明確標記,讓沒有安裝重相依的環境能略過而非整批錯誤——驅動層
      模組在裸環境下 import 得起來的性質必須維持(見 `AGENTS.md` 與 M3 的做法)
      → 裸 `python3`:2 passed / 7 skipped,skip 理由直接點名直譯器用錯
- [x] `pytest` 與 `test_sim.py` 兩套仍全綠(**用 `.venv/bin/python` 跑**,見 `AGENTS.md`)
      → pytest 80 → **89 passed**,test_sim 24 passed
- [x] 額外:把「純色塊偵測不到」變成測試。這是 harness 設計的地基前提,原本只是
      `PLAN.md` §6 的一句主張,現在有可執行的證據,也讓上面「偵測到臉」的斷言
      不是空過的
