# Part 3 · 第 4 章：配置 Ruby 系统并运行（msi_caches.py + simple_ruby.py）

> 对应脚本：`configs/learning_gem5/part3/msi_caches.py`、`simple_ruby.py`、`ruby_test.py`

## 本章目标

把 SLICC 生成的控制器组装成可运行的 Ruby 系统，跑一个多线程负载。

## 0. 检查并构建 MSI 协议

先检查实际构建配置，不能仅凭目录名判断是否启用 MSI。源码中 `RUBY_PROTOCOL_MSI` 默认关闭（`Kconfig: default n`），且**没有现成的 build_opts**，
需要自己建一个。参照 `build_opts/X86_MI_example`：

```bash
# 新建 build_opts/X86_MSI
cat > build_opts/X86_MSI <<'EOF'
RUBY=y
PROTOCOL="MSI"
RUBY_PROTOCOL_MSI=y
BUILD_ISA=y
USE_X86_ISA=y
EOF

# 编译（目录名 = build_opts 文件名）
scons build/X86_MSI/gem5.opt -j4 --linker=lld
```

## 1. msi_caches.py 做了什么

把 SLICC 生成的 C++ 控制器（`MSI_L1Cache_Controller`、`MSI_Directory_Controller`）
包装成 gem5 SimObject，并组装成 `RubySystem`。

### MyCacheSystem(RubySystem)

下面的协议能力检查为建议写法：检查键对应的值，而不只检查键是否存在；当前源码片段可能仍使用成员存在性检查。

```python
class MyCacheSystem(RubySystem):
    def __init__(self):
        if not buildEnv.get("RUBY_PROTOCOL_MSI", False):   # 编译时必须带 MSI 协议
            fatal("This system assumes MSI from learning gem5!")
        super().__init__()

    def setup(self, system, cpus, mem_ctrls):
        self.network = MyNetwork(self)               # 点对点网络
        self.number_of_virtual_networks = 3          # 分离三类协议消息的依赖
        # 每个 L1 缓存一个控制器 + 一个目录控制器
        self.controllers = [L1Cache(system, self, cpu) for cpu in cpus] + \
                           [DirController(self, system.mem_ranges, mem_ctrls)]
        # 每个 CPU 一个 sequencer（桥接 CPU 与 Ruby）
        self.sequencers = [RubySequencer(version=i, dcache=..., ruby_system=self)
                           for i in range(len(cpus))]
        ...
        self.network.connectControllers(self.controllers)  # 连网络
        for i, cpu in enumerate(cpus):
            self.sequencers[i].connectCpuPorts(cpu)        # 连 CPU
```

### L1Cache(MSI_L1Cache_Controller)

```python
self.cacheMemory = RubyCache(size="16KiB", assoc=8, start_index_bit=...)
self.clk_domain = cpu.clk_domain
self.connectQueues(ruby_system)   # 创建 MessageBuffer 并连到网络
```

### DirController(MSI_Directory_Controller)

```python
self.directory = RubyDirectoryMemory(block_size=ruby_system.block_size_bytes)
self.memory = mem_ctrls[0].port     # 目录直接对接 DRAM
self.connectQueues(ruby_system)
```

### 关键概念：Sequencer

`RubySequencer` 是 **CPU 和 Ruby 之间的翻译层**：把 CPU 的访存请求变成 Ruby 的
`RubyRequest`，塞进控制器的 `mandatoryQueue`，再把响应送回 CPU。

## 2. simple_ruby.py：两个 CPU 跑 threads 程序

```python
system.cpu = [X86TimingSimpleCPU() for i in range(2)]   # 2 个 CPU
system.mem_ctrl = MemCtrl(); ...                        # DDR3
system.caches = MyCacheSystem()
system.caches.setup(system, system.cpu, [system.mem_ctrl])

binary = ".../tests/test-progs/threads/bin/x86/linux/threads"  # 多线程、伪共享负载
```

跑的是 `threads` 程序——一个**故意制造 false sharing** 的多线程负载，
用来「压」协议，观察缓存间的一致性流量（MSI 下两个核反复抢同一个缓存块）。

## 3. ruby_test.py：随机测试器

```python
system.tester = RubyTester(checks_to_complete=100, wakeup_frequency=10, num_cpus=2)
```

用 `RubyTester` 做**随机一致性测试**：随机发读写请求，校验协议是否满足一致性
（每个地址读到的值必须符合某个合法的写序），是验证协议正确性的标准手段。

## 4. 运行

```bash
# 在仓库根目录执行

# 多线程一致性压测
build/X86_MSI/gem5.opt configs/learning_gem5/part3/simple_ruby.py

# 随机一致性测试
build/X86_MSI/gem5.opt configs/learning_gem5/part3/ruby_test.py
```

## 5. 附：MI_example 变体（有现成 build_opts）

`ruby_caches_MI_example.py` 用的是 gem5 内置的 `MI_example` 协议（只有 M/I 两态，
更简单），有现成 `build_opts/X86_MI_example`，直接：

```bash
scons build/X86_MI_example/gem5.opt -j4 --linker=lld
# 按下方 R5 步骤 5 创建启动脚本后，使用此 build 运行该启动脚本
```

## 分步实验 R5：先验证协议，再分析性能

**重点逻辑：构建选择协议 → Python 组装控制器 → 测试器检验数据 → trace 解释状态转移。编译成功不代表协议正确，随机测试通过也不等于形式化证明。**

### 步骤 1：构建前检查

确认 `build_opts/X86_MSI` 是否已存在，存在时先阅读，不要直接覆盖。按前文配置创建独立 build，使用 `scons build/X86_MSI/gem5.opt -j4`；`--linker=lld` 仅在已安装 lld 时添加。

核对 `src/learning_gem5/part3/Kconfig` 和 build 配置中的 MSI 开关。错误地检查 `buildEnv` 是否含键可能漏掉值为 false 的情况；缺少控制器类型时先检查构建能力，不要先改协议动作。

### 步骤 2：运行短随机测试

```bash
build/X86_MSI/gem5.opt --outdir=m5out/learning/r5_random --debug-flags=ProtocolTrace --debug-file=protocol.log configs/learning_gem5/part3/ruby_test.py
rg -n 'Transition|Load|Store|GetS|GetM|Data' m5out/learning/r5_random/protocol.log
```

确认退出原因来自测试完成，且没有数据检查失败、panic 或死锁。该脚本设置全局 tick 频率为 1ns，不能套用其他实验的默认 tick 换算。

### 步骤 3：增加测试长度

复制 `ruby_test.py` 为同目录 `ruby_test_lab.py`，只把 `checks_to_complete=100` 改为 `1000`，输出到 `r5_random1000`。先关闭大量 trace 完成正确性检查，失败时再打开 trace 缩小定位。保持种子固定便于复现；覆盖更多随机序列时用 `gem5.opt --help` 确认本构建提供的种子选项。

### 步骤 4：运行 CPU 多线程负载

```bash
build/X86_MSI/gem5.opt --outdir=m5out/learning/r5_threads configs/learning_gem5/part3/simple_ruby.py
```

先确认测试二进制存在及退出正常，再看共享行上的所有权转移。对比两个 CPU 的请求及目录流量；不要把与单核系统的时间差全部归因于一致性，因为负载与系统组成也不同。

### 步骤 5：正确使用 MI_example 变体

`ruby_caches_MI_example.py` 是控制器配置模块，不是完整启动脚本。若做 MI 实验，复制 `simple_ruby.py` 为同目录新脚本，把 `from msi_caches import MyCacheSystem` 改为 `from ruby_caches_MI_example import MyCacheSystem`，再使用对应 MI build 运行新脚本。先核实该模块的能力检查与当前 buildEnv 一致。

**验收**：短/长随机检查记录、一份 CPU trace 和 R3/R4 对应的状态表。进入 NoC 性能研究前必须先建立这个协议正确性基线。
