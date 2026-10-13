# Part 2 · 第 1 章：编写最简单的 SimObject（SimpleObject）

> 对应源码：`src/learning_gem5/part2/simple_object.{hh,cc}` + `SimpleObject.py`
> 配置脚本：`configs/learning_gem5/part2/run_simple.py`

## 本章目标

从零写一个 gem5 的 SimObject，理解 SimObject 的**「双层结构」**：
Python 参数层 + C++ 实现层，以及它们是怎么被构建系统串起来的。

## SimObject 由 3 类文件组成

| 文件 | 作用 |
|------|------|
| `SimpleObject.py` | Python 侧定义：声明类型名、指向哪个 C++ 类 |
| `simple_object.hh` | C++ 类声明（继承 `gem5::SimObject`） |
| `simple_object.cc` | C++ 实现（构造函数里打印一句话） |
| （`SConscript`） | 注册这个 SimObject 和它的源码 |

## 关键：Python 侧的三个「魔法字段」

```python
# SimpleObject.py
class SimpleObject(SimObject):
    type = "SimpleObject"                                 # 注册到 m5.objects 的名字
    cxx_header = "learning_gem5/part2/simple_object.hh"   # 对应 C++ 头文件
    cxx_class = "gem5::SimpleObject"                      # 完整 C++ 类名（含命名空间）
```

`type` 决定了脚本里 `from m5.objects import SimpleObject` 能拿到这个名字；
`cxx_header` / `cxx_class` 告诉 gem5 真正干活的 C++ 类在哪。

## C++ 侧

```cpp
// simple_object.cc —— 构造时就打印一句话
SimpleObject::SimpleObject(const SimpleObjectParams &params) :
    SimObject(params)
{
    std::cout << "Hello World! From a SimObject!" << std::endl;
}
```

注意：每个 SimObject 的 C++ 构造函数都要接收一个 `XxxParams` 引用并传给基类。
`XxxParams` 是由 gem5 构建系统根据 `.py` 文件里的参数**自动生成**的。

## SConscript 注册

```python
# src/learning_gem5/part2/SConscript
SimObject('SimpleObject.py', sim_objects=['SimpleObject'])  # 注册 Python 定义
Source('simple_object.cc')                                  # 编译 C++ 源码
```

## 运行

```bash
# 在仓库根目录执行
build/X86/gem5.opt configs/learning_gem5/part2/run_simple.py
```

配置脚本极简：只建一个 `Root`，挂一个 `SimpleObject`，没有 CPU 也没有内存。

```
root = Root(full_system=False)
root.hello = SimpleObject()
m5.instantiate()
m5.simulate()
```

## 实际输出与要点

```
Hello World! From a SimObject!     👈 构造函数里 std::cout 打印的（instantiate 阶段）
Beginning simulation!
Exiting @ tick 18446744073709551615 because simulate() limit reached
```

**要点**：因为没有注册任何 event，`simulate()` 没有任何事件可处理，会一路跑到
最大 tick（`2^64 - 1 = 18446744073709551615`）才因「到达 simulate 上限」退出。
这引出了下一章的核心概念——**事件(event)**才是让模拟前进/结束的动力。

## 分步实验 C1：证明 Python 对象对应 C++ 实例

**重点逻辑：Python 类型声明由构建系统生成绑定和 Params；配置创建对象，instantiate 阶段构造 C++ 实例。只有修改 C++ 行为时，才需要重新编译才能看到新行为。**

### 步骤 1：运行最小对象

```bash
build/X86/gem5.opt --outdir=m5out/learning/c1_one configs/learning_gem5/part2/run_simple.py
```

检查构造输出在 `Beginning simulation!` 之前还是之后；查看 `config.ini` 中的 `root` 与 `hello`。本例没有 CPU/内存，说明 SimObject 并不等于完整计算机系统。

### 步骤 2：建立四文件映射

在 `SimpleObject.py` 找 `type/cxx_class/cxx_header`，在头文件找构造函数，在 `.cc` 找实现，在 `SConscript` 找 `SimObject` 与 `Source`。写出“哪项错误会造成导入失败、编译失败、头文件找不到”的区别。

### 步骤 3：增加第二个实例

复制 `run_simple.py` 为同目录的 `run_simple_lab.py`，在 `m5.instantiate()` 前加入：

```python
root.second = SimpleObject()
```

```bash
build/X86/gem5.opt --outdir=m5out/learning/c1_two configs/learning_gem5/part2/run_simple_lab.py
```

预期构造输出出现两次，配置中出现两个独立对象。没有新增类型、没有改 C++，所以这步不需要重建。

### 步骤 4：让 C++ 输出对象身份

在 `simple_object.cc` 原有输出中加入 `name()`，区分两个实例；然后增量构建并重新运行：

```bash
scons build/X86/gem5.opt -j4
build/X86/gem5.opt --outdir=m5out/learning/c1_names configs/learning_gem5/part2/run_simple_lab.py
```

预期输出出现两个不同的对象路径。若仍是旧消息，核对构建是否成功、运行的是否是同一 build 目录下的二进制。

**验收**：四文件职责表、两个实例的配置与输出、解释为什么没有业务事件时不会发生实际工作。下一章用事件主动驱动工作与退出。
