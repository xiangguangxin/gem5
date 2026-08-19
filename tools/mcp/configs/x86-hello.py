"""
最小 gem5 X86 SE 仿真脚本（供 gem5 MCP 的 ``gem5_simulate`` 工具默认调用）。

在 X86DemoBoard 上跑 "hello world" 静态二进制，验证「编译 → 仿真」闭环。

用法
----

```
scons build/X86/gem5.opt -j`nproc`
./build/X86/gem5.opt tools/mcp/configs/x86-hello.py
```
"""

from gem5.prebuilt.demo.x86_demo_board import X86DemoBoard
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator

board = X86DemoBoard()

board.set_se_binary_workload(
    obtain_resource("x86-hello64-static", resource_version="1.0.0")
)

simulator = Simulator(board=board)
simulator.run()
