# 06 — 讓 LLM 自主處理不確定的 Care Cue

**What to build:** 將疑似哭泣、異常表情或明顯情緒變化表示成不確定的 Care Cue，讓 LLM 根據
Trigger Evidence 自主決定詢問、重新觀察、保持距離、不介入或結束，而不是執行固定安慰腳本。

系統只能描述可觀察 signal，不得把 classifier label 當成情緒診斷。當使用者的明確言語與視覺
推論衝突時，必須尊重使用者自我陳述並適當澄清。

**Blocked by:** 05

**Status:** resolved

- [x] temporal visual evidence 可形成帶不確定性的 Care Cue，不輸出已確診的 emotion fact
- [x] 疑似哭泣但未說話的 scenario 允許詢問、觀察、保持距離或不介入等可接受結果集合
- [x] 沒有任何規則把 Care Cue 直接映射成 approach、安慰台詞或固定 Tool sequence
- [x] LLM 可依 Evidence 選擇使用便宜 target observation 或較昂貴 scene inspection
- [x] 視覺看似微笑但使用者明確說難過時，後續回應尊重言語並承認視覺不確定性
- [x] 未經邀請的 movement 不是驗收成功的必要條件，且不得因展示功能而強制發生
- [x] Demo 至少提供「疑似哭泣」與「表情／言語衝突」兩個內建案例
- [x] Journal 顯示 Evidence、Decision Note、選用的感知／互動 Tool 與 ending
- [x] scripted-model assertions 驗證禁止診斷、禁止固定靠近及合理終止，不比對唯一台詞

## Answer

完成同一 anonymous track 上的 temporal Care gate：至少三張 frame、持續時間與 sequence-average
confidence 都達門檻後，才把縮眼、張口、低頭或嘴角抬高等可觀察 geometry 形成不確定 Care Cue。
Evidence 只帶 bounded selected JPEG crop、signal facts、時間與 uncertainty，不輸出 emotion label、
哭泣判定或心理診斷；單張 frame 與弱 sequence 都不會觸發。

Tool Registry 新增 read-only `observe_target` 與 `inspect_scene`。兩者回傳 typed kind、cost、ending、
age、freshness、structured facts 與 uncertainty，無可用 track 時明確回 `unavailable`；它們沒有移動
權限。Gate 沒有 Care Cue → approach／安慰話術映射，同一 cue 的 acceptance coverage 證明 model
可以重新觀察、檢查場景、詢問或直接 `done`。

Demo care 卡現在可執行兩個共用 synthetic visual fixtures。第一個展示持續可觀察 signal；第二個
在首次 perception Tool 後收到本人「我其實很難過」的明確言語，下一 Turn 尊重自我陳述並承認
視覺不確定性。畫面由當次 Runtime 與 Journal 顯示 Evidence、Decision Note、Tool、Observation 與
ending。Detector signals、model decisions、後續言語與 robot effect 都是腳本／模擬；未使用真實
相機或 Misty II，亦不構成情緒辨識準確率證據。
