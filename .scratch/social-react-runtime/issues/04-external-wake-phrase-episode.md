# 04 — 用 Hey/Hi Misty 啟動語音 Episode

**What to build:** 在外部裝置的 AV 音訊路徑上辨識 `Hey Misty` 與 `Hi Misty`，只有成功喚醒後才
擷取一段 bounded utterance、進行 VAD／ASR，並透過 SocialAgentRuntime 開啟一次 Episode。

第一版不啟用 Misty 內建 wake recognition 或聲源方向。這避免和既定 AV streaming 路徑產生未經
硬體驗證的資源切換，同時防止 idle ambient speech 持續送往 hosted ASR。

**Blocked by:** 02

**Status:** resolved

- [x] 外部 wake detector 接受 `Hey Misty` 與 `Hi Misty`，大小寫和合理停頓不造成不必要失敗
- [x] 沒有 wake phrase 的 ambient speech 不開 Episode，也不送往 hosted ASR
- [x] wake 成功後只擷取一段受 silence timeout、最大時長與 queue capacity 限制的 utterance
- [x] transcript、wake metadata 與時間形成 Explicit Request Trigger Evidence 並進入第一個 Turn
- [x] 重複 wake、空 utterance、ASR timeout、ASR error 與 backlog 都有有界且可觀察的結果
- [x] 音訊 queues 有 backpressure，不會因 hosted round trip 緩慢而無界累積
- [x] Demo 可上傳或選用音訊 fixture，並顯示 wake、capture、ASR、Episode 與 ending
- [x] fixtures 覆蓋兩個 wake phrases、false triggers、不同語速、silence 與 negative controls
- [x] LiveInputAdapter 的 vendor AV 路徑保留 `hardware-unverified` 標示，不宣稱已在 Misty 上運作
- [x] 預設測試使用本地 fixtures 和 scripted ASR，不需網路或硬體

## Answer

完成一條外部 AV 音訊垂直路徑：`AudioStream` 以 bounded queues 產生 VAD segments，
`LiveInputAdapter` 使用本機 PocketSphinx 辨識 Hey／Hi Misty，只有成功喚醒才做一次 bounded
hosted ASR，並把 wake metadata 與 transcript 送進第一個 Turn。所有非成功 ending 及 backlog
都有 typed Runtime records。

Demo 的 greeting card 可選四段 checked-in synthetic WAV，每次重新跑 VAD／wake detector；ASR、
model 與 robot 明確標示為 scripted／simulated，因此不需 API key 或網路。正式 vendor composition
已接上同一 adapter，但本專案沒有 Misty II；麥克風、AV transport、threshold 與真實房間表現均未
經硬體驗證。
