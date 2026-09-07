# 当前项目状态

## 仓库基线

- 当前 HEAD：`ec54c2d docs: 2026-09-06 batch — ops fixes, org feature gates, platform console, check-in tiers`
- 前一个重要提交：`3f26d4d`，修复 Nginx 对 `index.html` 和缺失 hashed asset 的缓存/回退问题。
- 最近业务提交：`030cd3e`，增加累计打卡 3 次送甜品券、5 次送 100 日元券。
- 工作区已知未跟踪：`store-admin-frontend/.claude/`。本次不处理。

## 已实现的业务能力

- 经营看板、日报、月次经营、进货、供应商、商品、库存、员工、排班、工资。
- Organization 多租户；`admin`、`branch`、`staff` 业务角色。
- 客户积分卡：登记、登录找回、二维码、积分、打卡、抽奖、券和核销。
- 活动星期/日期区间/优先级；当天按命中规则选择活动。
- 每日首次打卡奖励，以及累计 3 次甜品券、累计 5 次 100 日元券。
- カウンター受付和クーポン利用均支持页内相机扫码；无权限时可手工输入。
- 日报金额千分位显示；月次经营已移除“臨時／時給スタッフ給与”。
- 平台超级管理员：跨 Organization 查看总体数据、管理机构功能开关、停用/启用账号。
- 总店账号不能执行扫码核销，并显示日文主提示。

## 超级管理员的边界

Django `is_superuser=True` 才是平台超级管理员，不等同于业务角色 `admin`。超级管理员登录后只能进入 `/platform/*` 控制台，不显示单店日报等运营页面。平台概要聚合所有 Organization 的机构、门店、账号、本月营业额、客户和活动数据。

机构功能关闭后，该机构下所有账号都受影响；直接访问页面会进入功能不可用页，直接请求 API 返回 `403 feature-disabled`。账号停用使用 Django `User.is_active`，不能停用自己或机构最后一个启用的 admin。

## 需要接手者确认的事项

- 生产服务器是否确实已运行当前 HEAD，而不是旧 commit；以服务器 `git rev-parse HEAD` 为准。
- 生产是否已执行 `organizations 0004`、`promotions 0008/0009` 迁移和打卡种子。
- 生产平台超级管理员的用户名、密码和组织归属必须由运营者确认，不要从文档猜密码。
- 正式域名、HTTPS、真实 `SECRET_KEY`、安全 Cookie、HSTS 和 `DEBUG=False`。
- 3/5 次打卡档位当前主要通过管理命令、Django admin 或 REST 管理，营销页面尚无完整档位编辑弹窗。
- 旧 `lottery` 是历史名单/导入模块；新积分营销逻辑在 `promotions`，不要混用模型。
