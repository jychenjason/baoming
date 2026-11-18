# 01: 走路骨架與測試基座

**What to build:** 一個能以 `docker compose up` 啟動的網站骨架：首頁說明這個服務、`/healthz` 確認資料庫可讀，SQLite 具備完整 schema，且測試能以 HTTP 整合層驅動整個應用。這是後續所有切片的地基。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `docker compose up -d` 後 app 容器啟動；以非 root 使用者執行、`restart: unless-stopped`、記憶體上限 256MB、日誌輪替 10MB×3
- [x] `/healthz` 在資料庫可讀時回 200；資料庫不可用時回 503
- [x] `/` 顯示網站說明與管理員登入入口，沒有公開活動目錄
- [x] 首次啟動自動建立活動、選項群組、選項、報名、報名選擇等資料表；SQLite 啟用 WAL 與 busy_timeout
- [x] app factory 可注入資料庫路徑、時鐘、數學題產生器、管理員密碼與 session 金鑰；正式啟動與測試共用同一條建立路徑
- [x] pytest 基座能為每個測試建立獨立暫存資料庫，並提供取得頁面、抽 CSRF token、送出表單、跟隨 redirect 的輔助
- [x] 至少一個首頁整合測試與一個 `/healthz` 測試通過
- [x] 日誌以結構化格式記錄方法、路徑、狀態碼與耗時，不記錄 IP
