# 代码清单

## 后端

目录：`store-admin-backend/`，Django + DRF。

主要 app：`accounts`、`organizations`、`branches`、`staff`、`dailyreports`、`dashboard`、`paymentmethods`、`purchasing`、`inventory`、`scheduling`、`wages`、`promotions`、`lottery`、`common`。

入口和基础设施：

- `config/urls.py`：全局 API 路由。
- `config/settings.py`：数据库、JWT、缓存、中间件和安全配置。
- `common/permissions.py`：角色和租户权限。
- `common/features.py` / `common/middleware.py`：机构级功能开关。
- `organizations/overview.py`：跨机构总览聚合。
- `promotions/services.py`：积分卡核心事务服务。

迁移重点：

- `accounts 0005`：业务 admin 与 Django superuser 分离。
- `organizations 0004`：机构功能开关。
- `promotions 0007`：消费确认 request id。
- `promotions 0008`：活动日期/星期/优先级及每日奖励字段。
- `promotions 0009`：累计打卡档位和领取记录。

管理命令重点：

- `seed_demo_data`
- `seed_promotions_demo`
- `seed_checkin_reward`
- `provision_organization`
- `expire_promotions_points`
- `purge_stale_promotion_customers`

测试文件按 app 放置，重点专项是 `promotions/tests.py`、`organizations/tests.py`、`accounts/tests.py`。

## 前端

目录：`store-admin-frontend/src/`，Vue 3 + TypeScript + Vite + Element Plus。

- `router/index.ts`：客户、kiosk、单机构后台、平台控制台路由和门禁。
- `stores/auth.ts`：JWT、当前账号、角色、机构功能。
- `api/*.ts`：HTTP 数据层和 DTO 转换。
- `layouts/AppShell.vue` / `GuestShell.vue`：后台与客户布局。
- `components/QrScanner.vue`：页内相机扫码。
- `components/MoneyInput.vue`：金额输入和千分位显示。
- `views/platform/`：平台总览与机构/账号管理。
- `views/PromotionsView.vue`：活动、客户和营销管理。
- `views/DailyReportView.vue`、`MonthlyAnalysisView.vue`：日报/月次经营。
- `nginx.conf`：SPA、API 代理、静态资源缓存策略。

## 不应混淆的文件

- `design_mockup.html` 是视觉参考，不是运行入口。
- 根目录中文 Markdown 多为历史方案/进度记录；当前状态以本目录和源码为准。
- `store-admin-backend/venv/` 是本地依赖环境，不属于业务代码清单。
