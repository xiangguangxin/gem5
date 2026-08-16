# Part 3 · 第 4 章：配置 Ruby 系统并运行（msi_caches.py + simple_ruby.py）

> 对应脚本：`configs/learning_gem5/part3/msi_caches.py`、`simple_ruby.py`、`ruby_test.py`

## 本章目标

把 SLICC 生成的控制器组装成可运行的 Ruby 系统，跑一个多线程负载。

## 0. 先编译 MSI 协议（当前 X86 build 没有）

`RUBY_PROTOCOL_MSI` 默认关闭（`Kconfig: default n`），且**没有现成的 build_opts**，
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

```python
class MyCacheSystem(RubySystem):
    def __init__(self):
        if not "RUBY_PROTOCOL_MSI" in buildEnv:   # 编译时必须带 MSI 协议
            fatal("This system assumes MSI from learning gem5!")
        super().__init__()

    def setup(self, system, cpus, mem_ctrls):
        self.network = MyNetwork(self)               # 点对点网络
        self.number_of_virtual_networks = 3          # 3 个 vnet（防死锁）
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
cd /home/guangxinxiang.linux/github/gem5

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
build/X86_MI_example/gem5.opt configs/learning_gem5/part3/ruby_caches_MI_example.py
```
