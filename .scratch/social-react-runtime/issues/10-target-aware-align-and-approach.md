# 10 — 完成 target-aware 對準與接近

**What to build:** 讓 LLM 只提出「接近目前 Interaction Target」的語意 intent，由 deterministic
controller 根據新鮮 bearing、distance、configuration 與 deadline，先轉動底盤對準，再以 bounded
Steps 接近指定距離範圍。

controller 每次只執行短 movement Step，等待動作後的新 Reading 再重新計算。頭部 yaw 不能再被
誤認為底盤已朝向人物。

**Blocked by:** 08, 09

**Status:** resolved

- [x] model-visible Tool schema 只表達 target-aware approach intent，不接受 velocity、angular velocity 或 motor duration
- [x] active target reading 提供新鮮 distance、bearing、timestamp 與不確定性
- [x] controller 在平移前先使 chassis 對準 target，而不是只轉動 head
- [x] 每個 movement Step 有最大幅度，完成後必須取得較新的 Reading 才能繼續
- [x] controller 依 distance error、arrival band、總 Step cap 與 wall-clock deadline 決定下一步或結束
- [x] SimulatedMistyAdapter 更新 chassis pose、target relative bearing 與 distance，使 closed loop 可收斂
- [x] approach 成功、無法對準、讀數 stale、超過 bounds 與 timeout 都回傳 typed result
- [x] Demo 顯示 target、chassis heading、head yaw、每個 Step 與距離變化
- [x] tests 覆蓋側面 target、先旋轉再前進、過近需後退、arrival、overshoot assumption 與不收斂
- [x] 所有 movement constants 標示 simulated 或 hardware-unverified，不宣稱真機安全

