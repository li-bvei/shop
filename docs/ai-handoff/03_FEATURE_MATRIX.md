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

## 当前未完成或需要业务决定

- 打卡 3/5 次档位在 REST/admin/命令可配置，但营销页面没有完整编辑 UI。
- 生产安全配置、正式域名 HTTPS 和服务器版本需要部署时确认。
- 前端仍有较大的构建 chunk，可后续拆包，不是当前功能阻塞。
- 早期方案中的一些匿名会话、复杂反作弊、POS 交易号联动未纳入当前第一版。
