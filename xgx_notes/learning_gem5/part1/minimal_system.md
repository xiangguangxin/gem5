# 最小系统：从运行到读懂配置

## 目标与源码

阅读 `configs/learning_gem5/part1/simple.py`，理解 X86TimingSimpleCPU、SystemXBar、MemCtrl 与 DDR3 的实例化及连接。再对照 `simple-arm.py`、`simple-riscv.py`，识别 ISA 特有配置。

开始前记录 `git rev-parse HEAD`，检查构建产物和 `tests/test-progs/hello/bin/x86/linux/hello`。已有 build 不保证支持后续所有模型。

```bash
# 在仓库根目录执行；需要时先构建，-j 按可用内存调整
scons build/X86/gem5.opt -j4
build/X86/gem5.opt --outdir=m5out/learning/minimal configs/learning_gem5/part1/simple.py
build/X86/gem5.opt --outdir=m5out/learning/two_level configs/learning_gem5/part1/two_level.py
```

`simple.py` 固定教学 hello 路径；`two_level.py` 接受可选的位置参数 binary。脚本是否提供缓存选项，应检查脚本和 `caches.py`，不要把别的脚本的参数直接套用。

## 阅读顺序

1. `System`：时钟、电压、`mem_mode` 与物理地址范围。
2. CPU 的取指口、数据口和 X86 中断相关连接。
3. `SystemXBar` 的请求侧与响应侧；它是模型化的交叉开关，不等同于详细 NoC。
4. `MemCtrl` 与 DRAM 接口：控制器和存储介质参数分别在哪里。
5. `SEWorkload`、`Process.cmd`、线程上下文及 `Root(full_system=False)`。
6. `m5.instantiate()` 与 `m5.simulate()`：创建模型实例与推进事件。

端口连接语句表达连接关系；请求与响应沿相反方向流动，不能把图中的单向箭头当作只有单向传输。

## 输出检查

| 文件 | 要回答的问题 |
|---|---|
| 终端输出 | 是否打印 hello？为什么退出？有无 fatal/panic？ |
| `config.ini` / `config.json` | CPU 类型、时钟、端口、内存范围是否与预期一致？ |
| `stats.txt` | 仿真时间、指令计数在哪里？是否存在多次统计转储？ |

仿真时间与运行 gem5 所花的宿主机时间不同。tick 是仿真时间单位，换算时读取实际频率，不能直接当作 CPU cycle。

## 练习与验收

- 分别定位两份配置中的 Cache 对象，画出连接差异。
- 改变时钟后检查实际配置，解释为何 DRAM 的所有时间参数不会自动同比缩放。
- 保存两组输出与退出原因；如果程序未完成，先修复运行错误。
- 用 hello 验证通路后，转入[实验方法](../experiments/README.md)，使用更合适的负载研究性能。

## 分步实验 A1：先证明配置真的生效

**重点逻辑：配置脚本 → 对象实例 → 端口连接 → 程序执行 → 输出证据。** 先能对应这五个环节，再考虑性能。

### 步骤 1：固定环境并运行基线

在仓库根目录执行以下命令；后文所有命令使用同一工作目录。

```bash
pwd
git rev-parse HEAD
file build/X86/gem5.opt tests/test-progs/hello/bin/x86/linux/hello
mkdir -p m5out/learning/a1
build/X86/gem5.opt --outdir=m5out/learning/a1 configs/learning_gem5/part1/simple.py > m5out/learning/a1/run.log 2>&1
cat m5out/learning/a1/run.log
```

没有构建产物时先按前文构建。检查日志中出现 hello 和正常程序退出原因；fatal、panic 或达到时间上限不能算程序完成。`file` 用来检查 ISA 和二进制类型，不表示依赖已经满足。

### 步骤 2：按实例顺序标注脚本

打开 `configs/learning_gem5/part1/simple.py`，依次圈出 `System`、`clk_domain`、`cpu`、`membus`、`mem_ctrl`、`process`、`root`。在每个赋值旁写一句职责，再把所有端口赋值抄成连接表。

回答：`system.system_port` 是不是 CPU 的正常取指口？`process.cmd` 指向的是宿主可执行程序还是模拟程序？CPU 的类型由哪一行决定？答案需要指到代码，而不是只给名词解释。

### 步骤 3：反查实际配置

```bash
rg -n '^\[|^type=|^clock=|^mem_mode=|^range=|^ranges=|^port=|^cpu_side_ports=|^mem_side_ports=' m5out/learning/a1/config.ini
rg -n 'simSeconds|simTicks|simFreq|numCycles|committedInsts|simInsts' m5out/learning/a1/stats.txt
```

只记录实际存在的字段；统计名变化时搜索描述。把脚本中的 `1GHz` 与输出时钟值对应，检查 `simTicks / simFreq` 与 `simSeconds` 是否一致。不要把整个系统的 tick 数当作 CPU 周期数。

### 步骤 4：做一次可预测的修改

复制 `simple.py` 到同目录 `simple_lab.py`，保留它对测试程序的相对路径。只把 `system.clk_domain.clock = "1GHz"` 改为 `"2GHz"`，用新的输出目录运行：

```bash
build/X86/gem5.opt --outdir=m5out/learning/a1_2ghz configs/learning_gem5/part1/simple_lab.py
```

先在配置中证明频率改变，再比较仿真时间。预期是 CPU cycle 时长改变；总时间不保证减半，因为内存访问和其他组件仍有自己的时间约束。

### 验收与排错

提交对象连接图、两次命令、退出原因、实际时钟及时间比较。没有 hello 先查程序路径/ISA；没有配置文件先查是否在实例化前退出；性能没按预期变化先检查配置是否生效，不要立刻改第二个参数。
