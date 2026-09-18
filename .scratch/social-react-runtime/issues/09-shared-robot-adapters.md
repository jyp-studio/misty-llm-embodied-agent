# 09 — 統一 Real 與 Simulated Robot Adapter

**What to build:** 讓 Tools 與 controllers 只依賴一個窄的 Robot Interface。RealMistyAdapter 將行為
轉成 vendor requests；SimulatedMistyAdapter 更新 pose、位置與世界結果，使後續 perception 能看見
動作後果，而不只是記錄呼叫。

用既有說話、表情、LED、頭部及手臂行為打通兩條 Adapter contract。Journal 仍在 ReAct／Tool
dispatch 層產生，不新增 RecordingRobot 或 RecordingTransport。

**Blocked by:** 01

**Status:** resolved

- [x] Robot Interface 足以承載既有 expressive Tools，但不向 model 暴露 vendor request 細節
- [x] SimulatedMistyAdapter 更新 expression、LED、head、arms、speaking state 與可觀察 world state
- [x] 模擬 effect 成功或失敗會影響後續 Snapshot/Observation，而非只留下 command log
- [x] RealMistyAdapter 產生符合既有 vendor contract tests 的 requests，但不需連接 Misty IP
- [x] 所有 real behavior、latency、calibration 與 reliability 都標示 `hardware-unverified`
- [x] Journal 是 model intent、validation、Tool result 與 effect 的唯一行為紀錄來源
- [x] 不建立 RecordingRobot、RecordingTransport 或與 Journal 競爭的第二份 event log
- [x] Demo 以 SimulatedMistyAdapter 重播說話、表情、LED、頭部與手臂變化
- [x] 同一個 scripted Episode 在兩個 Adapter contract 上使用相同 Tool/controller code path
- [x] refactor 過程保持既有測試綠，且不修改無關的 user-owned changes

