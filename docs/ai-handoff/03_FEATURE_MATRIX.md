# 需求实现矩阵

状态含义：已实现表示源码和历史测试覆盖；部署状态仍需按服务器实际环境复核。

| 需求 | 当前状态 | 关键位置 |
|---|---|---|
| 日报金额千分位逗号 | 已实现 | `src/components/MoneyInput.vue`、`DailyReportForm.vue`、`utils/format.ts` |
| カウンター受付新页面 | 已实现 | `src/components/AppSidebar.vue`，新标签页打开 `/kiosk/verify` |
| 客户/主页面认证期限 | 已决策 | 客户 card token 不过期；后台 JWT 按 access/refresh 生命周期运行 |
| 活动按平日/周末/黄金周 | 已实现 | `Campaign`、promotions migration 0008、`resolve_active_campaign` |
| 每日首次打卡送券 | 已实现 | `record_checkin`、`verify_spend`、`seed_checkin_reward` |
| 3 次送甜品、5 次送 100 日元 | 已实现 | `CheckinMilestone`、migration 0009、seed 默认值 |
| 柜台相机扫码 | 已实现 | `QrScanner.vue`、`KioskVerifyView` |
| クーポン使用相机扫码 | 已实现 | `QrScanner.vue`、`KioskRedeemView` |
| 月次经营移除临时/时薪工资 | 已实现 | `dashboard/analysis.py`、`MonthlyAnalysisView.vue`、导出逻辑 |
| 平台超级管理员总体掌握 | 已实现 | `organizations/overview.py`、`organizations/views.py`、`platform` 前端页 |
| 按机构功能一键开关 | 已实现 | `OrganizationFeature`、`common/features.py`、平台管理页 |
| 直接链接访问提示联系管理员 | 已实现 | 功能路由门禁、`FeatureUnavailableView.vue`、API 403 |
| 停用对应账号权限 | 已实现 | `User.is_active`、`guard_account_deactivation`、平台/设置账号开关 |
| 总店账号禁止扫码核销 | 已实现 | promotions views 的 `head-office-account-cannot-scan` 错误码及 kiosk 提示 |
| 新建第二个机构并测试多分店 | 已覆盖测试 | `organizations/tests.py` 有跨机构平台总览、账号停用和功能开关测试；生产数据需另行确认 |
| 进货筛选/翻页数秒延迟 | 已实现 | `purchasing/views.py` `month_total` action，前端 `fetchPurchaseMonthTotal` |
| 进货同日多条记录排序 | 已实现 | `PurchaseRecordViewSet.filter_queryset` 补 `-id` 兜底排序 |
| 价格履历/涨跌对比长期为空（数据 bug） | 已修复 | `backfill_item_name_normalized` 命令，已在生产执行 |
| 价格履历对比口径改为"上次进货"，历史默认只显示近2月 | 已实现 | `compute_prior_purchase_deltas`、`PurchasingView.vue` 历史抽屉 |
| 进货品目联想不提示是否新商品 | 已实现 | `PurchasingView.vue` `isNewItem` + 新商品提示 |
| 进货 IME 回车误提交/数量单价可空提交 | 已实现 | `handleRowEnter` 组字保护、`commitRow` 数量/单价校验 |
| 进货批量替换（多条件组合） | 已实现 | `purchasing/views.py` `bulk_replace` action，`purchasing/tests.py` 6+3 个用例 |
| 2026年进货明细与 Excel 对比补漏 | 已执行 | `reconcile_purchases_2026` 命令，生产已跑（453 条，验证幂等） |
| 日报报销明细缩放/窄屏可读性 | 已实现 | `DailyReportForm.vue` `.expense-row` 最小宽度 + 自动换行 |
| 日报报销联想词不自动带金额 | 已实现 | `DailyReportForm.vue` `handleSelectSuggestion` |
| 日报打印自适应单页、隐藏0元支付方式 | 已实现 | `usePrintFit`、`DailyReportForm.vue` `pm-zero-print-hide` |
| 日报"下载PDF"（独立于打印，离屏紧凑排版，不截图编辑表单，深色模式下也是白底黑字） | 已实现（2026-09-22，待部署） | `DailyReportView.vue` `buildDailyReportPdf`/`handleDownloadPdf`，`utils/pdfExport.ts` `el`/`renderOffscreenToPdf`，`DailyReportForm.vue` `cashRegisterDenominationBreakdown` |
| 日报 PDF 日期星期、收银机前日遗留/本日新增差额拆分 | 已实现（2026-09-22，待部署） | `DailyReportView.vue` `reportDateWithWeekday`/`shiftReportDate`/`buildDailyReportPdf`；前一自然日无数据时不推测本日新增差额 |
| 手机端底部导航 / 日报手机表单 / 仕入れ手机录入 | 已实现（2026-09-25，待提交部署） | `components/mobile/*`、`composables/useIsMobile.ts`、`useNavItems.ts`、`utils/purchaseEntry.ts`；桌面路径未改 |
| 顾客卡去 Emoji + 转盘按后端 `prize_id` 落点（spin-wheel、confetti、减少动效、奖品加载失败重试） | 已实现（2026-09-25，待提交部署） | `WheelOfFortune.vue`、`GuestCardView.vue`、`api/guest.ts` `DrawResult.prizeId`、`promotions/views.py` `_draw_result_body` |
| 日报离线保存与冲突处理 | 已实现 | `utils/dailyReportDraft.ts`、`DailyReportView.vue` 同步/冲突逻辑 |
| 首页问候语按时间变化 | 已实现 | `AppShell.vue` `greetingKey()` |
| 全局屏蔽鼠标滚轮改数字输入框 | 已实现 | `main.ts` 全局 `wheel` 监听 |
| 超管账号出现在企业自己账号列表（权限漏洞） | 已修复 | `UserViewSet.get_queryset`、`PlatformOrganizationUsersView` 均加 `is_superuser=False` |
| 企业停用（`Organization.active`）未生效 | 已实现 | `OrganizationScopedJWTAuthentication`、`OrganizationScopedTokenObtainPairSerializer` |
| 平台超管跨企业账号/分店管理、新建企业 | 已实现 | `organizations/views.py` Platform* 系列 view、`PlatformFeaturesView.vue` |
| 日报零钱默认数量 + レジ固定金額可改（默认值只加算不预填，且有 2026-09-15 日期线保护旧日报） | 已实现 | `dailyreports/models.py` `CashRegisterDefaults`、`views.py` `CashRegisterDefaultsView`、`DailyReportForm.vue` `computeCashRegisterTotal`/`CASH_REGISTER_DEFAULTS_CUTOFF_DATE`、前端 `api/cashRegisterDefaults.ts` |
| 旧日报锁定 + 企业共享密码解锁（仅本次编辑会话有效） | 已实现 | `dailyreports/report_lock.py`、`views.py` `ReportUnlockView`/`DailyReportViewSet._enforce_report_lock`、`organizations/models.py` `report_unlock_password_hash`、`accounts/views.py` `OrganizationView`、前端 `api/reportLock.ts`、`DailyReportView.vue` 解锁流程、`DailyReportForm.vue` `readonly` prop、`SettingsView.vue` 密码管理卡片 |
| 仕入先管理按月筛选、历史月份手动金额与恢复自动计算 | 已实现 | `SupplierMonthlyPayableOverride`、purchasing migration 0008、`SupplierViewSet.monthly_payable`、`SuppliersView.vue` |
| 心斋桥仕入品目生成梅田店联想种子（不复制财务交易） | 已实现 | `PurchaseItemSeed`、`seed_purchase_catalog --source shinsaibashi --target umeda`、`PurchaseRecordViewSet.suggestions` |
| 仕入先管理/仕入管理供应商数据是否同步 | 已确认无问题 | 两处共用同一张 `purchasing.Supplier` 表，无重复模型；未做代码改动 |
| 部署后页面缓存导致功能异常，需强刷才生效 | 已实现（部分） | `Dockerfile` 构建时写 `public/version.txt`，`utils/versionCheck.ts` 轮询 + `App.vue` 提示条；仅覆盖本仓库内 nginx 这一层，生产外层宝塔 Nginx 的缓存配置未核实，不在本次改动范围 |
| 密码强度统一 + 登录限流（P1-05） | 已实现 | `accounts/services.py` `validate_new_password`、`accounts/throttling.py`、`config/settings.py` `AUTH_PASSWORD_VALIDATORS`/`login_ip`/`login_account`；前端 `SettingsView.vue`/`PlatformFeaturesView.vue` 补了弱密码报错的静默失败 |
| 积分抽奖返还流水逐笔余额错误（P1-07） | 已修复 | `promotions/services.py` `draw_lottery`，`DrawLotteryServiceTests` 新增逐行 `balance_after` 断言 |

## 当前未完成或需要业务决定

- 打卡 3/5 次档位在 REST/admin/命令可配置，但营销页面没有完整编辑 UI。
- 生产安全配置、正式域名 HTTPS 和服务器版本需要部署时确认。
- 前端仍有较大的构建 chunk，可后续拆包，不是当前功能阻塞。
- 早期方案中的一些匿名会话、复杂反作弊、POS 交易号联动未纳入当前第一版。
- `docs/ai-handoff/05_TESTS_AND_RISKS.md` 记录的 P1-02/P1-04/P1-05/P1-06/P1-07（进货负数口径、部署脚本回滚方式、密码强度、生产安全配置现场验证、积分流水语义）都是需要业务负责人决策或较大范围改动的项，本次会话未处理。
