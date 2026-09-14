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
| 日报离线保存与冲突处理 | 已实现 | `utils/dailyReportDraft.ts`、`DailyReportView.vue` 同步/冲突逻辑 |
| 首页问候语按时间变化 | 已实现 | `AppShell.vue` `greetingKey()` |
| 全局屏蔽鼠标滚轮改数字输入框 | 已实现 | `main.ts` 全局 `wheel` 监听 |
| 超管账号出现在企业自己账号列表（权限漏洞） | 已修复 | `UserViewSet.get_queryset`、`PlatformOrganizationUsersView` 均加 `is_superuser=False` |
| 企业停用（`Organization.active`）未生效 | 已实现 | `OrganizationScopedJWTAuthentication`、`OrganizationScopedTokenObtainPairSerializer` |
| 平台超管跨企业账号/分店管理、新建企业 | 已实现 | `organizations/views.py` Platform* 系列 view、`PlatformFeaturesView.vue` |
| 日报零钱默认数量 + レジ固定金額可改 | 已实现 | `dailyreports/models.py` `CashRegisterDefaults`、`views.py` `CashRegisterDefaultsView`、前端 `api/cashRegisterDefaults.ts`、`DailyReportForm.vue` |

## 当前未完成或需要业务决定

- 打卡 3/5 次档位在 REST/admin/命令可配置，但营销页面没有完整编辑 UI。
- 生产安全配置、正式域名 HTTPS 和服务器版本需要部署时确认。
- 前端仍有较大的构建 chunk，可后续拆包，不是当前功能阻塞。
- 早期方案中的一些匿名会话、复杂反作弊、POS 交易号联动未纳入当前第一版。
- `docs/ai-handoff/05_TESTS_AND_RISKS.md` 记录的 P1-02/P1-04/P1-05/P1-06/P1-07（进货负数口径、部署脚本回滚方式、密码强度、生产安全配置现场验证、积分流水语义）都是需要业务负责人决策或较大范围改动的项，本次会话未处理。
