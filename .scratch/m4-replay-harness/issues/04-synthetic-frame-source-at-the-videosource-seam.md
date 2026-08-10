# 04 — 在 VideoSource seam 上做合成影格來源

**What to build:** 說「使用者現在在 137 公分處」,就能拿到一張真的 MediaPipe 偵測得到
人臉、而且量出來的距離就是 137 公分的影格。

這是整個 harness 的地基。真值不是另外估的,是**由建構方式決定的**:把一張 CC0 人臉圖
按「該距離對應的臉寬像素數」縮放後貼到畫布上,而那個像素數由校正常數(焦距、假設臉寬)
反算得出。所以真值精確已知,量測誤差不會混進被量的對象裡。

實作為 `VideoSource` 的第二個 adapter(第一個是 M3 的 RTSP 串流)。**這是 M4 的唯一
注入點**,也是 M3 那個 Protocol 從「假想 seam」變成「真 seam」的時刻。

為什麼不用純色塊:MediaPipe 偵測不到,而繞過 MediaPipe 則把主因假設掉——MediaPipe
每幀 30–50ms 的耗時正是造成積壓的原因,那是被量的現象本身。這也正是 `test_sim.py`
的 `FakePerception` 犯的錯。

**這一張必須自我驗證。** 如果合成器本身有偏差,後面所有延遲數字都不可信。

**Blocked by:** 02(需要可獨立 import 的臉部偵測來做自我驗證)

**Status:** ready-for-agent

- [ ] 一個滿足 `VideoSource` 的合成來源:`start` / `stop` / `read` / `flush` / `backlog`
      全部有意義的實作,不是 noop
- [ ] 給定目標距離,能算出對應臉寬像素數並產生該畫面
- [ ] 產出的影格帶擷取時間戳,與 M3 的 `CapturedFrame` 同一種時鐘
- [ ] **自我驗證測試**:掃一組距離,對每一個都斷言「真的臉部偵測量出來的距離」與
      「合成時指定的真值」在容差內一致。這條不過,harness 就沒有意義
- [ ] 完全離線、確定性:素材納入版控,任何隨機性有固定 seed
- [ ] `pytest` 與 `test_sim.py` 兩套仍全綠
