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

2026-09-13～15 这批没有新增 migration（`Organization.active`、`is_superuser` 过滤、批量替换都是用已有字段/新 API，不是新表）。

管理命令重点：

- `seed_demo_data`
- `seed_promotions_demo`
- `seed_checkin_reward`
- `provision_organization`：CLI 版一次性建企业；核心逻辑已抽到 `organizations/services.py`，平台"新建企业"UI 调的是同一份 service。
- `expire_promotions_points`
- `purge_stale_promotion_customers`
- `purchasing/backfill_item_name_normalized`：一次性修复 `bulk_create()` 导入历史数据漏算 `item_name_normalized` 的问题，幂等，可安全重跑。
- `purchasing/reconcile_purchases_2026`：一次性对比 `2026注文書.xlsm`（不在仓库里，读 `import_data/order_form_2026.json`）与现有进货记录，只插入缺失行；硬编码 `BRANCH_ID='shinsaibashi'` 和 `PROTECTED_DATE='2026-09-13'`，改分店/保护日期要改代码常量，不是命令行参数。

新增/关键后端文件（本轮）：

- `common/authentication.py`：`OrganizationScopedJWTAuthentication`，在 simplejwt 基础上加一条"所属 Organization 被停用则拒绝"检查，配置在 `settings.REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`。
- `accounts/serializers.py` `OrganizationScopedTokenObtainPairSerializer`：登录时做同样检查，避免"能登录但下一个请求就被拒"的体验。
- `organizations/services.py`：`provision_organization`、`create_branch_for_organization`，CLI 命令和平台 UI 共用。
- `purchasing/services.py` `compute_prior_purchase_deltas`：价格履历"对比上次进货"的计算，和原有 `compute_price_comparisons`（月均价，供涨跌筛选用）是两套并行逻辑，不要合并。

测试文件按 app 放置，重点专项是 `promotions/tests.py`、`organizations/tests.py`、`accounts/tests.py`、`purchasing/tests.py`（`BulkReplaceTests` 覆盖多条件组合/校验/分店隔离）。

## 前端

目录：`store-admin-frontend/src/`，Vue 3 + TypeScript + Vite + Element Plus。

- `router/index.ts`：客户、kiosk、单机构后台、平台控制台路由和门禁。
- `stores/auth.ts`：JWT、当前账号、角色、机构功能。
- `api/*.ts`：HTTP 数据层和 DTO 转换。
- `layouts/AppShell.vue` / `GuestShell.vue`：后台与客户布局。
- `components/QrScanner.vue`：页内相机扫码。
- `components/MoneyInput.vue`：金额输入和千分位显示。
- `views/platform/`：平台总览与机构/账号管理；`PlatformFeaturesView.vue` 现在还管跨企业分店和"新建企业"。
- `views/PromotionsView.vue`：活动、客户和营销管理。
- `views/DailyReportView.vue`、`MonthlyAnalysisView.vue`：日报/月次经营。
- `views/PurchasingView.vue`：进货录入/筛选/价格履历/批量替换，本轮改动最大的前端文件之一。
- `utils/dailyReportDraft.ts`：日报离线草稿的 localStorage 读写，`DailyReportView.vue` 依赖它做保存失败兜底和联网后同步。
- `nginx.conf`：SPA、API 代理、静态资源缓存策略。

## 不应混淆的文件

- `design_mockup.html` 是视觉参考，不是运行入口。
- 根目录中文 Markdown 多为历史方案/进度记录；当前状态以本目录和源码为准。
- `store-admin-backend/venv/` 是本地依赖环境，不属于业务代码清单。
