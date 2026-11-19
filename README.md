# 活動報名系統（BaoMing）

自架式活動報名與名單管理網站。管理員建立活動並設定報名選項，參加者透過活動專屬連結報名；系統使用 SQLite 儲存活動與報名資料。

## 功能

- 管理員可建立、編輯、開放、關閉、複製及刪除活動。開放中的活動必須先手動關閉才能刪除。
- 可設定必填或選填的自訂選項群組、選項價格與顯示順序。
- 參加者不需建立帳號；透過加法驗證後，可報名並查看公開名單。
- 報名者可用原瀏覽器的簽章 cookie 找回和更新自己的報名。
- 管理員可代為新增、修改或刪除報名，並匯出 CSV 或 JSON。
- 提供 SQLite 備份、資料還原及部署更新工具。

## 快速部署

需要 Docker Engine 與 Docker Compose v2。預設 Compose 設定會啟動 Caddy，透過網域自動提供 HTTPS；請先將網域 DNS 指向主機，並允許對外 TCP 80、443（以及 UDP 443）。

```sh
cp .env.example .env
```

編輯 `.env`，設定唯一的 `ADMIN_PASSWORD`、隨機 `SESSION_SECRET` 及 `DOMAIN`。可用下列命令產生 session secret：

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
chmod 600 .env
docker compose up -d --build
```

完成後，前往 `https://你的網域`，並使用 `ADMIN_PASSWORD` 登入管理介面。資料庫會保存在 `data/`；請勿刪除或公開該目錄、`.env`、`backups/` 或匯出檔。

如果要部署到 Google Cloud Compute Engine，或改用 HTTP，請依照 [部署與維運手冊](DEPLOYMENT.md) 操作。HTTP 會以明文傳送密碼、session cookie 及報名資料，只適合暫時或私有環境。

## 文件

- [使用手冊](USER_GUIDE.md)：管理活動、報名名單及匯出資料。
- [部署與維運手冊](DEPLOYMENT.md)：GCP/VPS 部署、HTTPS/HTTP 設定、更新、備份與還原。
- [產品規格](spec.txt)
- [領域詞彙表](GLOSSARY.md)

## 本機開發

Python 3.12+ 可安裝開發相依套件並執行測試：

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

應用程式以 `app.main:create_app` 建立 FastAPI app；正式部署建議使用上方的 Docker Compose 設定。
