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
cd /home/guangxinxiang.linux/github/gem5
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
