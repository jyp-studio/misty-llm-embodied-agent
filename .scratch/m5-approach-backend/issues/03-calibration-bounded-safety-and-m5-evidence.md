# 03 — 在明示校準假設內守住模擬安全底線

**What to build:** 讓公開 `approach()` 在明示的驅動校準誤差假設內，不因前進或後退步長造成可預見的安全底線突破或來回震盪；再以 M4 的同一套 latency 與 robustness 方法產出 M5 的最終證據。

安全主張必須是條件式的。新增一個明示為 UNCALIBRATED 的最大實際移動倍率假設，代表實際行走距離相對命令距離的上界。控制律依此預留 headroom，並至少覆蓋 M4 已重現的 `2.0×` 校準誤差反例。這證明的是該假設範圍內的模擬行為，不是真機安全認證。

前進與後退必須共享清楚的有界步長語意。非預設 tolerance、gain 或 minimum step 不得重新喚醒既有的前進越線或後退超衝；runtime、reachability 分析、robustness sweep 與測試都呼叫唯一的正式控制律，不在測試裡重寫公式。

**Blocked by:** 02 — 使用移動後新讀數完成一次有界 approach

**Status:** ready-for-agent

- [ ] 設定明示最大實際移動倍率假設，標記為 UNCALIBRATED，並說清楚超出假設後行為未知
- [ ] 控制律以該倍率限制前進命令，確保假設成立時實際移動不越過 configured safety floor
- [ ] M4 已重現的 `2.0×` 校準誤差場景透過公開 approach 行為執行後，不再低於 45cm 模擬安全底線
- [ ] 前進與後退都具有有界步長；minimum step 不得強迫任一方向跨過抵達帶或造成可預見震盪
- [ ] 覆蓋會喚醒既有缺陷的非預設 tolerance、gain 與 minimum-step 組合，並從外部觀察是否收斂及是否越線
- [ ] Runtime、reachability 分析、robustness sweep 與測試共用同一個正式控制律，測試不得手抄控制公式
- [ ] `arrived` 只表示在抵達帶內且未曾突破模擬 safety floor；安全異常不得被成功狀態掩蓋
- [ ] 正式管線重跑 M4 latency bound 並保持綠燈；數字仍明確標示為 process 內量測
- [ ] 以正式 approach 與新控制律重跑 transport-lag robustness sweep，報告新的收斂邊界、第一個失敗模式與第一個 safety-floor breach
- [ ] 人可讀報告明確區分「量測」、「參數掃描」、「條件式模擬保證」與「未實機驗證」
- [ ] 報告保留 `approach_user()` 從未在硬體執行的事實，不把 synthetic replay 描述成真機結果
- [ ] M5 的計畫與交接文件更新為實際完成狀態，記錄任何偏離，但不順手展開 Audio、視覺模型或 ReAct loop
- [ ] 全套 pytest 使用專案 `.venv` 執行且零 skip；既有 simulation runner 保持綠燈
- [ ] 提交前檢查整個 staged diff，只包含 M5 與 tracker 更新，不納入工作樹中原有的無關修改
