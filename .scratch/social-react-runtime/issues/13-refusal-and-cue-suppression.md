# 13 — 尊重拒絕並抑制重複打擾

**What to build:** 當目前 Interaction Target 明確表示想獨處或不要靠近時，Misty 停止追問與 movement，
有禮貌地完成 Episode，並對同一匿名 track 的非明確 Cue 啟用短期 Cue Suppression。之後新的
Explicit Request 可以立即繞過 suppression。

Suppression 是有期限的互動節流，不是跨 Episode 人物記憶，也不能依 face identity 延長。

**Blocked by:** 06, 08, 11

**Status:** resolved

- [x] 明確拒絕會使 LLM 停止非必要追問，controller 停止或不開始 approach
- [x] Episode 以尊重界線的可接受 ending 完成，不要求唯一台詞
- [x] 完成後為同一匿名 track 建立有期限且可觀察的 Cue Suppression
- [x] suppression 期間相同 Care Cue 或 Social Invitation 不會立刻重開 Episode
- [x] 新的 Explicit Request 可以繞過 suppression 並建立新的 Episode
- [x] suppression 到期、track 消失或 runtime shutdown 都會清理相關 state
- [x] suppression record 不含姓名、face embedding 或跨 session personal identity
- [x] Demo 顯示拒絕、movement stop、suppression 倒數、被抑制 cue 與 explicit bypass
- [x] fake-clock tests 覆蓋 TTL 邊界、重複 cue、不同匿名 track 與 explicit bypass negative control

## Answer

明確拒絕不由 Runtime 以關鍵字判定。Persona 要求 model 在對方明確要求空間時停止追問並不再接近；
model 自行選擇 typed `respect_boundary` Tool，該 Tool 呼叫共用 `Robot.halt()`、結束 Episode，並在
`EpisodeOutcome` 留下 `boundary_respected`。台詞不固定。

`SocialAgentRuntime` 只在該 outcome 後建立 suppression，內容僅有 run-local 匿名 track token 與
`cue_suppression_s` 截止時間。同 track 的 Care Cue／Social Invitation 留下 `cue_suppressed` 而不開
Episode；不同 track 不受影響；新的 Explicit Request 留下 bypass record、清除 suppression 並立即排程。
TTL 到期、視覺 gate 回報空場景、shutdown 與 run 結束都留下 typed clear record。

Care card 的 `respect-boundary` fixture 顯示回應、halt、30 秒倒數、被抑制 cue 與 explicit bypass。
fake-clock tests 覆蓋 TTL 邊界、重複 cue、不同匿名 track 與 explicit bypass negative control。
