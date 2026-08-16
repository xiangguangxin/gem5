# Part 1 · 第 3 章：给配置脚本添加缓存（Adding Caches）

> 对应源码：`configs/learning_gem5/part1/caches.py`、`two_level.py`
> 上一章对照：`simple.py`（CPU 直连内存，无缓存）

## 本章目标

在 `simple.py` 的基础上，在 CPU 和内存之间插入两级缓存（L1I/L1D + L2），
理解 gem5 里缓存是怎么作为 SimObject 创建、并通过「端口(port)」连接起来的。

```
simple.py:    CPU ──────────────► membus ──► DDR3
two_level.py: CPU ─► L1I/L1D ─► l2bus ─► L2 ─► membus ─► DDR3
```

## 核心概念

### 1. Cache 是一个 SimObject

`Cache` 定义在 `src/mem/cache/` 下（Python 侧是 `src/mem/cache/Cache.py`），
和 `System`、`CPU`、`MemCtrl` 一样都是 SimObject，在脚本里 `from m5.objects import Cache`
即可使用。自定义缓存就是**继承 `Cache` 并覆盖类属性/方法**。

### 2. 端口（Port）的连接语义（本章最容易绕晕的点）

每个缓存有**两个端口**：

| 端口 | 方向 | 含义 |
|------|------|------|
| `cpu_side`  | 朝向 CPU | 请求端口（requestor / master 侧），发出内存请求 |
| `mem_side`  | 朝向内存 | 响应端口（responder / slave 侧），接收请求 |

总线（XBar）也有两组端口：`cpu_side_ports`（接请求方）和 `mem_side_ports`（接响应方）。

**连接规则**：请求方的 `mem_side` 连到 响应方的 `cpu_side`。
即「上一级的出口」接「下一级的入口」：

```python
# L1 的出口(mem_side) 接 l2bus 的入口(cpu_side_ports)
self.mem_side = bus.cpu_side_ports          # L1Cache.connectBus

# L2 的入口(cpu_side) 接 l2bus 的出口(mem_side_ports)
self.cpu_side = bus.mem_side_ports          # L2Cache.connectCPUSideBus

# L2 的出口(mem_side) 接 membus 的入口(cpu_side_ports)
self.mem_side = bus.cpu_side_ports          # L2Cache.connectMemSideBus
```

### 3. 两级缓存的层次结构

`caches.py` 里的类继承关系：

```
Cache (gem5 内置)
 ├─ L1Cache          assoc=2, tag/data/response_latency=2, mshrs=4, tgts_per_mshr=20
 │    ├─ L1ICache    size="16KiB"   connectCPU → cpu.icache_port
 │    └─ L1DCache    size="64KiB"   connectCPU → cpu.dcache_port
 └─ L2Cache          size="256KiB", assoc=8, latency=20, mshrs=20, tgts_per_mshr=12
```

L1 采用**指令/数据分离**（Harvard 结构），各自独立；L2 是统一的（unified）。

### 4. two_level.py 的连接拓扑（完整链路）

| 组件 | 类型 | 连接 |
|------|------|------|
| CPU | `X86TimingSimpleCPU` | icache_port / dcache_port |
| L1I / L1D | `L1ICache` / `L1DCache` | cpu_side←CPU, mem_side→l2bus |
| l2bus | `L2XBar()` | 连接 L1 与 L2 |
| L2 | `L2Cache` | cpu_side←l2bus, mem_side→membus |
| membus | `SystemXBar()` | 连接 L2 与内存 |
| 内存 | `MemCtrl()` + `DDR3_1600_8x8()` | 范围 512MiB |

## 常用缓存参数（见 `src/mem/cache/Cache.py`）

| 参数 | 含义 | L1 默认 | L2 默认 |
|------|------|---------|---------|
| `size` | 缓存容量 | 16KiB(I) / 64KiB(D) | 256KiB |
| `assoc` | 组相联路数（associativity） | 2 | 8 |
| `tag_latency` | 读 tag 延迟（cycle） | 2 | 20 |
| `data_latency` | 读数据延迟（cycle） | 2 | 20 |
| `response_latency` | 命中时总响应延迟（cycle） | 2 | 20 |
| `mshrs` | Miss Status Holding Registers 数量（可同时处理多少未命中） | 4 | 20 |
| `tgts_per_mshr` | 每个 MSHR 最多合并多少个后续目标 | 20 | 12 |

## 运行方式

```bash
cd /home/guangxinxiang.linux/github/gem5

# 默认跑 hello 程序
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py

# 通过命令行覆盖缓存大小（caches.py 用 SimpleOpts 暴露了这些参数）
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py \
    --l1i_size=32KiB --l1d_size=32KiB --l2_size=512KiB

# 指定要执行的二进制
build/X86/gem5.opt configs/learning_gem5/part1/two_level.py binary=/path/to/prog
```

## 实验对比（有缓存 vs 无缓存）

同一段 hello 程序：

| 脚本 | 缓存 | 模拟结束时刻 (tick) |
|------|------|---------------------|
| `simple.py`  | 无缓存（直连内存） | ~507,962,000 |
| `two_level.py` | 两级缓存 | ~58,125,000 |

加了缓存后程序**约快 9 倍**完成（tick 越小越早结束）。
原因：CPU 大部分访存命中了 L1，避免了每次都要走 DRAM 的几百个 cycle 延迟。
可以进一步用统计输出（`m5out/stats.txt` 里的 `system.cpu.dcache.overallMissRate`
等）量化验证缓存命中率与加速。
