# 部署与种子运行手册

## 已确认的生产服务器位置

生产项目目录已经确认，不是待补充信息：

```text
/www/wwwroot/shop
```

历史记录中的生产服务器为 `43.132.201.45`。后续 AI 不得再以“不知道服务器目录”为由拒绝编写或执行部署步骤。如果当前执行环境没有服务器登录权限，应准确说明“缺少 SSH/终端权限”，而不是说服务器位置未知。

## 最近一次生产部署

- 日期：2026-09-17
- 提交：`b6247a1 purchasing: support monthly overrides and branch item seeds`
- 路径与命令：`cd /www/wwwroot/shop && bash deploy.sh`
- 迁移：`purchasing.0008_suppliermonthlypayableoverride_purchaseitemseed_and_more` 已成功应用。
- 验证：backend/frontend 容器重建成功，`python manage.py check` 无错误。
- 梅田店品目种子已执行：

  ```bash
  cd /www/wwwroot/shop
  docker compose exec -T backend python manage.py seed_purchase_catalog --source shinsaibashi --target umeda
  ```

  首次写入 540 项；之后用相同命令加 `--dry-run` 复核为 `0 create, 0 update`。该命令只写 `PurchaseItemSeed`，不会复制 `PurchaseRecord`，不会影响梅田店材料费。

## 本地上传代码到 GitHub

已确认的 GitHub 远端和分支：

```text
GitHub: git@github.com:li-bvei/shop.git
remote: origin
branch: main
```

在本地项目根目录检查变更，只暂存本次任务明确涉及的文件，然后提交并上传到 GitHub：

```bash
cd /Users/tatsuya/Documents/Projects/shop
git status --short
git add <本次修改的明确文件路径>
git diff --cached --stat
git diff --cached
git commit -m "说明本次修改"
git push origin main
```

如果用户明确表示“把当前项目的全部本地修改一起上传”，可以使用下面这组完整命令：

```bash
cd /Users/tatsuya/Documents/Projects/shop
git status --short
git branch --show-current
git remote get-url origin
git add -A
git diff --cached --stat
git commit -m "update project"
git push origin main
```

正常上传成功后，GitHub 仓库 `li-bvei/shop` 的 `main` 分支会包含新提交，生产服务器随后通过 `git pull --ff-only origin main` 拉取。

不要在没有确认范围时无条件使用 `git add .` 或 `git add -A`，避免把用户尚未完成或与本次任务无关的修改一起上传。执行 `git push` 前需要确认当前分支为 `main`、暂存内容和测试结果；AI 只有在用户明确要求上传时才执行推送。如果 `git push` 报 SSH 权限错误，应说明缺少本机 GitHub SSH 认证，不得说 GitHub 地址未知。

## 生产服务器拉取并部署

登录生产服务器后，使用以下固定命令：

```bash
cd /www/wwwroot/shop
git pull --ff-only origin main
docker compose up -d --build
```

这是项目此前实际使用的部署方式。`--ff-only` 用于避免服务器工作树自动产生合并提交；如果拉取失败，应先检查服务器上的分支、未提交修改和远端差异，不能改用 `git reset --hard` 或强制覆盖。

部署完成后至少执行：

```bash
cd /www/wwwroot/shop
git rev-parse HEAD
docker compose ps
docker compose logs --tail=100 backend frontend
```

如本次包含 Django migration，再执行：

```bash
cd /www/wwwroot/shop
docker compose run --rm backend python manage.py migrate
docker compose up -d
```

## 本地检查

```bash
cd store-admin-backend
source venv/bin/activate
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
```

前端：

```bash
cd store-admin-frontend
npm run type-check
npm run build
```

## Docker 部署顺序

在项目根目录执行：

```bash
docker compose build backend frontend
docker compose up -d db
docker compose run --rm backend python manage.py migrate
docker compose up -d backend frontend
docker compose exec backend python manage.py seed_checkin_reward --org 1
```

用户要求的旧演示数据命令仍可用：

```bash
docker compose exec backend python manage.py seed_promotions_demo
```

打卡奖励种子命令幂等，默认是 3 次甜品券、5 次 100 日元券、有效期 7 天；可用 `--expires-days`、`--dessert-at`、`--voucher-at`、`--voucher-yen`、`--daily-reward` 调整。正式执行前确认 `--org` 或 `--branch` 范围。

## 上线后检查

- `docker compose ps` 中 db/backend/frontend 均健康。
- `/api/auth/me/` 返回 `enabledFeatures`、`isSuperuser`。
- 普通 admin 访问 `/api/platform/overview/` 应为 403；平台超级管理员应能看到跨机构总览。
- 关闭一个机构的 inventory 后，旗下账号菜单隐藏、直接 API 返回 `feature-disabled`。
- 停用账号后，用旧 access token 请求 API 也应被拒绝。
- 本部账号打开两个 kiosk 页面应看到日文禁止扫码提示；分店账号能使用相机/手工输入。
- `index.html` 不应长期缓存；缺失的 hashed asset 应返回 404，不应返回 SPA HTML。

## 生产安全不可省略

使用真实随机 `SECRET_KEY`、`DEBUG=False`、正确 `ALLOWED_HOSTS`，并配置 HTTPS、SSL Cookie、CSRF Cookie、HSTS 和可信代理。不要把 `.env`、数据库备份或真实账号密码写进交接文档。

## 旧设备说明

iOS 9 的 Safari/Chrome 打开空白属于浏览器能力不足：Vue 3 依赖 ES2015 Proxy，且当前 Vite 目标面向现代 Safari。项目实际建议 iOS 14+；若要支持 iOS 12/13，需要单独引入 legacy 构建并全面回归，iOS 9 不建议投入兼容成本。
