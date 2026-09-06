# 08 — demo 伺服器與內建範例

**What to build:** 執行一條指令，瀏覽器自己打開，四個 golden Episode 可以選，時間軸看得到。

**零新相依。** 標準庫的 `http.server` 綁在 localhost、`webbrowser` 自動開啟、手寫
HTML/CSS/JS。不使用任何 web framework 或前端框架：`requirements.txt` 是一份有論述的文件
（每個被移除的套件都寫了理由），為了一個 demo 頁面往回加相依會讓那份論述變弱。

內建範例用 `tests/goldens/` 那四份，因為它們涵蓋 Episode 的四種結束方式，而且來歷有完整記載。
**畫面上必須標明它們是規格、寫在實作之前** —— 不得讓觀看者誤認為某次真實執行的紀錄。這正是
這個專案最值得講的一件事，不該在展示它的地方被含糊帶過。

**Blocked by:** 04, 07

**Status:** ready-for-agent

- [ ] 一條指令啟動，瀏覽器自動打開，不需要記網址或埠號
- [ ] **零新相依**：`requirements.txt` 不變
- [ ] HTTP 處理是一個純函式（method、路徑、內容進，狀態、標頭、內容出），不開 socket 就測得到
- [ ] socket 與瀏覽器啟動是薄殼，與 `main()` 同性質
- [ ] 四份 golden 可以在頁面上選擇並顯示
- [ ] 畫面明確標示範例是「規格，寫在實作之前」
- [ ] 只綁 localhost
- [ ] 全套測試綠且零 skip
