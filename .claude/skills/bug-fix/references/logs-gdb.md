# 日志与 GDB 定位

## 日志：重建一条事务，不盲目扩大输出

先保留原始错误和退出码，再用 `rg -n 'panic|fatal|assert|error' run.log` 找线索并读前后文。没有匹配不能证明无错。每次实验使用独立输出位置，记录命令、代码版本、配置和种子。新增日志优先放在边界和不变量附近，记录输入/输出、对象或事务标识、队列、状态前后值；不要解引用可能失效的指针来打印。

gem5 按包地址/块地址、Request/Packet、控制器、消息类型、tick 关联，必要时加入事务 ID；同一地址可有多笔请求，指针也可能复用。查首次偏离而非只查最后 panic。

```bash
# 示例：实际二进制和配置必须存在且匹配；先用 --debug-help 核对 flag。
build/X86/gem5.debug --debug-help
build/X86/gem5.debug --outdir=/tmp/gem5-debug-run \
  --debug-flags=HelloExample --debug-file=trace.log \
  configs/learning_gem5/part2/hello_goodbye.py
```

`/tmp/gem5-debug-run` 只是示例，应换成独立目录；trace 通常写在 outdir。大日志可按支持的 debug-start/debug-end 缩小 tick 窗口，先核对本地 help。Ruby 对照消息发送/接收、状态转换、TBE 与 ack 计数；完全阻塞缓存对照 blocked、retry 和响应完成；事件对照 when、scheduled 与对象寿命。

## GDB：先保留现场，再追上游

用匹配当前源码、带调试信息的二进制。优化可能使变量显示 `<optimized out>`，不能据此推断未初始化。需要时按项目构建流程生成 debug 版本，保留原始触发条件。

```bash
gdb --args build/X86/gem5.debug configs/learning_gem5/part2/hello_goodbye.py
```

进入 GDB 后：

```gdb
set pagination off
run
# 信号或断点停止后先采集：
bt full
info threads
thread apply all bt full
frame 0
info args
info locals
list
up
```

`bt` 从当前最内层栈帧向调用方展示；`frame N` 切换观察位置。找到第一个相关业务栈帧，核对参数及调用方如何生成它们。SIGABRT 顶层常是 abort/断言处理；真正违反不变量的位置在调用链中。栈损坏时回溯可能不完整；一份栈只是某个时刻的快照，不是完整事件历史。

针对一个假设逐步选用（替换示例名称与行号，不能整段盲贴）：

```gdb
break file.cc:123
break 'Namespace::Class::method'
info breakpoints
# N 替换为真实断点编号；条件变量须在该断点作用域内。
condition N count < 0
continue
next
step
finish
print count
# 地址有效、对象寿命明确后，监视何处改变值：
watch -location obj->count
# C++ 异常需要定位抛出点时：
catch throw
```

`print` 优先读字段；表达式中的函数调用可能改变目标状态。watchpoint 有数量/大小/作用域和平台限制，软件 watchpoint 较慢；重跑或对象销毁后应重新确认地址与监视点，不监视已释放对象。不能把新增日志或断点后不再出现的竞态当修复。

卡死时先 Ctrl-C 暂停，再查看所有线程栈；检查锁/条件变量、事件队列是否还有事件、请求是否在等待 retry/ack。gem5 协议卡住时宿主线程仍可能正常执行，必须结合 tick 进度、状态机和消息缓冲定位等待环。Attach 仅用于获授权目标；通常直接启动自己的复现进程即可。

已有 core 时：

```bash
gdb /path/to/exact-matching-binary /path/to/core
```

再运行 `thread apply all bt full`。core 必须与二进制/库匹配；系统不一定生成 core，先核对现有收集设置。core 可含完整进程数据，不自动纳入 Git 或长期记忆。

GDB 若因 ptrace/容器限制失败，记录具体错误和缺失证据，不擅自放宽系统权限。可用受支持环境重现，或先做日志与静态分析。

## 权威参考

- [GDB Backtrace](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Backtrace.html)
- [GDB 官方手册：Breakpoints / Watchpoints / Catchpoints](https://sourceware.org/gdb/current/onlinedocs/gdb/)

命令以本地 `help` 为准，本文不要求安装最新 GDB。
