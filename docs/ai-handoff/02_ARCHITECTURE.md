# 系统架构与关键流程

## 拓扑

```text
浏览器 / 平板
  └─ Vue 3 + Vite SPA
       ├─ /pc/*       客户积分卡页面
       ├─ /kiosk/*    店员平板核销与相机扫码
       ├─ /platform/* 平台超级管理员控制台
       └─ /           单机构运营后台
            └─ Nginx /api/ 反向代理
                 └─ Django + DRF + Simple JWT
                      └─ MySQL 8
```

## 后端边界

| 模块 | 责任 |
|---|---|
| `organizations` | Organization、平台总览、机构功能开关 |
| `accounts` | User、登录、账号状态、偏好 |
| `branches` | 分店主数据 |
| `dailyreports` | 日报和历史快照 |
| `dashboard` | 看板、月次经营聚合 |
| `inventory` / `purchasing` | 商品库存、供应商、进货 |
| `staff` / `scheduling` / `wages` | 员工、排班、工资 |
| `promotions` | 当前积分卡、活动、打卡、奖品、抽奖、券、风控 |
| `lottery` | 历史抽奖名单/导入，不是新营销抽奖引擎 |

API 总入口在 `store-admin-backend/config/urls.py`。跨模块权限和机构功能门禁在 `common/permissions.py`、`common/features.py`、`common/middleware.py`。

## 认证与权限

- 后台账号：`/api/token/`、`/api/token/refresh/`，Simple JWT access 约 8 小时、refresh 约 7 天。
- 客户：`pc_guest` Cookie + `X-Guest-Token`，`card_token` 是不可猜的稳定令牌，当前不设过期；价值操作仍由店员核销约束。
- 页面菜单隐藏不是安全边界；后端 ViewSet 权限、租户过滤和功能中间件必须同时成立。
- 客户公开接口不受机构订阅开关影响，否则客户无法查看自己的卡片。

## 积分卡主流程

```text
客户登记/找回
  → Customer + card_token
  → 店员扫描二维码
  → 后端按当天星期/日期/优先级选择 Campaign
  → 首次打卡写 CheckInRecord
  → 发每日奖励券、累计档位券、积分
  → 客户端查看券/积分
  → 店员扫描券并核销
```

关键业务服务在 `store-admin-backend/promotions/services.py`；相机实现是前端 `QrScanner.vue`，使用 `getUserMedia` + 懒加载 `jsqr`，不跳到系统相机 App。
