# 窗帘兼容适配（fork 分支）

本分支让 HA 的 `cover` 实体复用现有 PID `008`（断路器）开关服务。
智慧生活预计显示开关/断路器界面，不是原生窗帘卡片。尚未完成实机云端注册和手机控制验证。
不修改 C SDK、华为产品 ID、已有绑定或网络发现规则。

## 行为

- 智慧生活开关开：调用 `cover.open_cover`。
- 智慧生活开关关：调用 `cover.close_cover`。
- `open`、`opening`、`closing` 上报开；完全 `closed` 才上报关。
- `unknown` / `unavailable` 不上报虚假的关状态，查询返回无状态。
- 缺少或非法 `on` 值不会触发关帘。不可用实体或不支持相应开/关能力时拒绝命令。
- 不支持通过此卡片停止或设置百分比；这两项仍需在 HA 操作。
- PID 008 的电量、电压等 HA 映射显式置空，避免关联窗帘设备上的无关传感器；应用仍可能显示该产品固定的电气字段。

## 识别与范围

适配器位于 `custom_components/hwhomebridge/config/adapters/compat/curtain.json`。
型号包含 `curtain`，或设备名称包含 `窗帘` / `curtain`，且设备拥有 `cover` 实体时可建立映射。
沿用原项目的型号/名称匹配优先级；已有更高优先级适配器可能优先匹配。
不按所有 `cover` 通配，因此普通车库门不会自动纳入。
实体必须属于 HA device；没有 device 的模板 cover 不在本次范围内。
沿用一个 HA device 对应一个桥接设备的结构：同一设备下多个 cover 仅映射第一个候选。

`enum_to_text_multi` 已由上游支持，适用于 select 选项转换。此方案直接调用 cover 服务，不需要把开关帘伪装成 select 文本。

## 部署与回退

1. 备份现有 `custom_components/hwhomebridge` 目录及 `.storage/hwhomebridge` 运行数据。
2. 从本 fork 的 `feat/curtain-compat` 分支取文件。已安装版本不一定与本分支基线一致，先检查差异，不直接覆盖运行数据。
3. 将 `custom_components/hwhomebridge` 集成目录部署到 HA 对应目录，重启 HA。
4. 检查桥接设备管理中是否列出窗帘、是否被排除，再验证智慧生活同步、开关帘及状态回报。
5. 回退时恢复备份的集成目录并重启；本分支不要求删除绑定或重新生成 PIN。

本次提交只提供代码与本地测试结果；部署、云端接纳、实体动作是独立验证步骤。

## 本地验证

需要 Python 3.9+ 和上游依赖 `aiofiles`，不加载 HA 初始化代码或原生 SDK。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 custom_components/hwhomebridge/validate_config.py
```

测试覆盖适配器合并、实体注册、完整控制路由到 HA service 调度、主动上报与 SDK 查询一致性、非法控制、不可用实体、能力限制、普通开关回归及无关 cover 排除。
