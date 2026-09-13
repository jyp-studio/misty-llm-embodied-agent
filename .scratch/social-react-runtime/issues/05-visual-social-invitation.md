# 05 — 以視線和揮手辨識 Social Invitation

**What to build:** 使用本地快速視覺感知，從短時間影像序列辨識人物存在、面向 Misty 與揮手等
可觀察 signal。只有形成 Social Invitation 候選時才選取少量 Evidence 交給模型決定是否互動。

空房間或只是路過、沒有看向 Misty 的人物必須保持安靜。這張票不把表情解讀成 Care Cue，也不
包含 approach。

**Blocked by:** 02

**Status:** resolved

- [x] 本地 visual gate 產生帶時間、confidence、匿名 track reference 與可觀察 facts 的候選 cue
- [x] 空房間 scenario 不產生 Episode
- [x] 有人物但未看向 Misty、沒有 gesture 的 scenario 不產生 Episode
- [x] 持續看向 Misty 並揮手的 temporal scenario 形成 Social Invitation
- [x] 只將 bounded selected frames 或 crops 放入 Trigger Evidence，不週期性上傳全部人物影像
- [x] multimodal model 自主選擇低風險回應或不互動；視覺 gate 不指定回應動作
- [x] 多張臉可維持不同匿名候選，且 cue 不因最新畫面任意跳到另一人
- [x] Demo 顯示 frame timeline、gate facts、selected Evidence、模型決策與簡單 Misty 回應
- [x] temporal gesture tests 不以單張 still image 冒充揮手驗證，並包含 gaze/gesture negative controls
- [x] 所有準確率與 real-camera 行為都標示 simulation/fixture evidence，而非硬體驗證

## Answer

完成 `VisualInputAdapter` 與本機 `LocalVisualGate`：同一匿名 track 必須在有限 gesture window
內同時累積持續注視、足夠的手部水平位移、方向變化與 sequence-average confidence，才產生
`SocialInvitation`。每個 frame 都留下 typed visual-attention record；空房、路過者、單張 still、
中斷注視、過期手勢與低 confidence sequence 都不開 Episode。

合格 cue 只選取目前 frame 的一張 bounded JPEG crop 進入第一個 multimodal Turn，完成後不在
Runtime result 保存 bytes。多人 detector signals 與 anonymous tracks 都採 one-to-one nearest
association，避免同一 face mesh／hand 被重複賦予不同人物。Gate 只決定是否詢問 model，不指定
Tool；測試涵蓋 model 低風險回應與直接 `done`。

Demo greeting card 新增四組共用 synthetic visual timelines，顯示 frame outcomes/facts、selected
Evidence metadata、scripted model Decision Note、模擬 Misty 回應與 ending；negative fixtures
明確顯示 model 未被呼叫。這些結果只證明 fixture/simulation orchestration。MediaPipe extractor
未經真實相機驗證，整條路徑從未連接 Misty II。
