# 08 — 鎖定 Interaction Target 並完成 A→B 交接

**What to build:** 讓每個 Episode 維持一個匿名且短期的 Interaction Target。A 與 Misty 互動時，
另一張更近或更清楚的臉不能讓 target 靜默切換；B 明確呼叫時先排隊，A 在安全的 Turn boundary
收尾後，B 才取得新的 Episode。

這張票建立 target ownership 與多人 handoff，不加入跨 Episode face identity 或 speaker direction。

**Blocked by:** 03, 05

**Status:** resolved

- [x] Episode 建立時從 Trigger Evidence 綁定一個匿名 Interaction Target
- [x] Snapshot、主動感知與 movement intent 都明確參照 active target
- [x] 多人物畫面中，較近、較大或最新的臉不會自動取代 active target
- [x] target 可進入 temporarily lost 與 reacquired 狀態，但重新取得必須符合原匿名 track 規則
- [x] A 的 Episode 期間 B 的 Explicit Request 會進入 queue，而不是平行開 Episode或被丟棄
- [x] A 在 Turn boundary 得到可理解的收尾後，B 才啟動新的 Episode 和新的 target
- [x] bumper、hazard stop 或 e-stop 仍可立即中止 physical effect，不必等一般 handoff
- [x] Demo 以兩個可辨識但匿名的 actors 顯示 target lock、queued B 與交接時間線
- [x] tests 包含 target-switch negative control、B queue、A ending、B start 與 stale B expiry
- [x] 不建立 face recognition identity，也不宣稱能以聲源方向判定 B 的位置

