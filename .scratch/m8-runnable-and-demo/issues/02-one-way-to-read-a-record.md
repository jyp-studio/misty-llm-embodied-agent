# 02 — prefactor：一筆紀錄怎麼讀，只說一次

**What to build:** 把「一筆 Journal 紀錄對人類讀起來是什麼」抽成一個被測試蓋到的結構，
`TerminalRenderer` 從它格式化。

**這是 prefactor，不交付使用者看得到的東西。** 理由是 07 的畫面資料需要回答同一個問題，
不先抽就會有兩份說法 —— 而這個專案剛因此付過學費：`TerminalRenderer` 對 `speak` 印出
`-> , 52cm away`，逗號前面是空的，因為只有 `approach` 的結果帶 `result` 這個鍵。那個 bug
不是沒被測到，是**測試蓋不到那一層** —— 既有測試斷言的是 Journal，不是印出來的字。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 「一筆紀錄說了什麼」是一個純函式，紀錄進、結構出，不含任何排版
- [ ] `TerminalRenderer` 從那個結構格式化，不再自己決定顯示什麼
- [ ] **每一種紀錄都有對應**，而且有測試證明新增一種紀錄卻忘記處理會變紅
- [ ] `speak`、`change_led`、`move_head` 等沒有 `result` 鍵的 Tool，其 Observation 讀起來
      是通順的 —— 不再有空的逗號
- [ ] `approach` 的 Observation 仍然讀得到它的四種狀態
- [ ] 陰性對照：一個對每種紀錄都回傳同一句話的實作，會被測試擋下來
- [ ] 全套測試綠且零 skip
