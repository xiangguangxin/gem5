# gem5 + SystemC：先验证事务桥接

> 本章给出接入步骤，具体外部 NPU 依赖需在实施时检查。

## 选择内核归属

| 方案 | 本地参考 | 主要检查 |
|---|---|---|
| SystemC 模型运行于 gem5 内 | `util/systemc/systemc_within_gem5/README` | 模型是否兼容 gem5 的 SystemC 实现及构建方式 |
| gem5 嵌入外部 SystemC | `util/systemc/gem5_within_systemc/README` | libgem5、C++ 配置、调度及外部库链接 |

如果现有 NPU 绑定外部 Accellera SystemC，先核对 API、ABI 和构建依赖；不能假定把两个运行时直接链接就能工作。外部方案的 README 明确要求构建 libgem5 时关闭 gem5 原生 SystemC 支持。选型记录应说明谁推进时间、何时返回、怎样退出。

## 从本地示例开始

原生方案的 README 使用 EXTRAS 构建示例。对当前 X86 构建可参考以下形式，执行前核对 build 是否启用 SystemC；不要同时改动正在使用的基线构建配置。

```bash
scons build/X86/gem5.opt -j4 EXTRAS=util/systemc/systemc_within_gem5/systemc_gem5_tlm
build/X86/gem5.opt --outdir=m5out/learning/tlm util/systemc/systemc_within_gem5/systemc_gem5_tlm/config.py
```

这组命令是接入练习入口，本文未保证它在所有环境直接通过。该配置使用 TrafficGen → Gem5ToTlmBridge32 → TLM_Target；它验证 gem5 到 TLM target 的方向，不等于已经实现 NPU DMA。

完成后重建若需去掉示例，应显式清空 `EXTRAS`，见本地 README。外部 SystemC 方案按其 README 使用独立构建目录操作。

## 分清两个方向

```text
控制：CPU / 测试驱动 → gem5 响应端口 → Gem5ToTlmBridge → NPU TLM target
数据：NPU TLM initiator → TlmToGem5Bridge → gem5 请求端口 → 互联 → MemCtrl
```

类型和参数见 `src/systemc/tlm_bridge/TlmBridge.py`；实现见同目录 `gem5_to_tlm.*`、`tlm_to_gem5.*`。NPU 若保留自己的 HBM target，应明确它是否属于独立存储域，不能同时让两套内存模型重复计算同一次访问。

## 接口契约

- 地址空间、读写命令、长度、byte enable、流式访问以及支持的事务类型。
- tick、SystemC 时间精度、模型 cycle 的转换与舍入。
- payload 数据缓冲、扩展及引用计数的所有权。
- 阻塞传输与非阻塞传输的对应关系；使用 AT 时核对 BEGIN_REQ / END_REQ / BEGIN_RESP / END_RESP 及返回状态。
- 最大在途事务、背压、响应顺序与错误码转换。
- 调试访问、DMI、atomic/functional 访问是否支持；未验证的能力需注明。

Socket 的 32/64 等类型参数不能直接当作模型已经实现相应的物理带宽。带宽约束需要具体时序与资源模型。

## 验收顺序

单笔写读校验 → 固定延迟检查 → 多笔请求 → 请求与响应背压 → 错误响应 → 结束时事务排空。记录两侧时间戳并确认没有重复计算延迟。

两个方向分别通过后，接入最小计算模块，再接完整 NPU；一旦挂起，优先缩回单笔事务检查调度与协议状态。

## 分步实验 E：分开验证两个桥接方向

**重点逻辑：先固定数据、固定延迟验证桥，再让 NPU 产生复杂事务；一次访问只能由选定模型承担一次延迟。**

### E1：做选型记录

写出当前 NPU 的 SystemC 来源、版本、构建方式、TLM LT/AT 接口，以及哪个内核推进时间。对照两个本地 README 选择方案。把模型依赖问题先缩到最小 SystemC 模块，不同时迁移完整 NPU。

### E2：运行已有正向示例

按前文 EXTRAS 命令编译并运行，保存构建命令、输出配置与退出原因。阅读示例 `config.py`：找 TrafficGen 的配置、桥的两侧连接与 target。先确认已有示例保持原状能够运行，再修改模型。

### E3：将正向请求缩成确定序列

创建独立测试配置/target，让测试发一笔已知地址写与读，核对数据。然后只增加固定 target 延迟，如 10ns 和 100ns，记录进入 target 和返回发起方的时间戳。显式检查响应状态；如果现有 target 不存真实数据，先为该实验实现小内存 target。

**通过条件**：读回正确、响应只完成一次、两种延迟的差值符合约定；不能用流量生成器正常退出代替读写数据校验。

### E4：反向访问 gem5 内存

实现最小 TLM initiator，经 `TlmToGem5Bridge` 连接 gem5 互联/内存。按“写入固定模式 → 等写完成 → 读回 → 比较 → 结束”执行。先一笔在途，再多笔；给每笔加独立 ID，区分完成顺序。

**通过条件**：能证明 DMA 方向实际经过 gem5 内存模型，而不是读到 target 内部的另一份数据。

### E5：检查协议边界

AT 模式逐笔记录 phase、sync 返回值、时间标注和引用计数；允许的 phase 简化或返回状态以桥实现为准。制造延后响应与资源不足，检查 payload/buffer 没有提前释放，排空后无悬挂事务。所有时间使用统一单位汇总。

### E6：只替换计算模块

保持 E3/E4 的控制与内存路径不变，接一个固定延迟的伪加速器，再替换为真实 NPU。每次只增加一个模块，比较事务数和时间差。出现挂起时回退到单笔事务复现，定位最后一条 phase/Packet，而非修改多处延迟碰运气。

**交付**：选型记录、两个方向的独立配置、数据校验、单笔与多笔时序图。E4/E5 尚未完成时，应明确平台只验证了部分接入路径。
