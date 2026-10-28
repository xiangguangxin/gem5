# Part 5 · Garnet 与片上网络

本部分专门记录 Garnet 的概念、官方资料导读、源码分析与网络实验。建议先完成 [Part 3 的 Ruby/MSI 学习](../README.md#一致性研究分支)，再从消息传输路径开始学习。

## 已有文档

| 顺序 | 文档 | 内容 |
|---|---|---|
| 1 | [Garnet 官方文档导读与源码地图](garnet.md) | 参数、拓扑与路由、VC/credit、路由器流水线、源码入口和实验建议 |
| 2 | [MSI 如何通过 Ruby Network 发送消息](msi_ruby_network.md) | GetM 的 SLICC 动作、队列连接、网络注册与接收事件，以及 Garnet 对应路径 |

## 后续记录方向

以下主题尚待补充，可随学习进展分别建立文档：

- 合成流量配置与运行：独立构建、流量模式和统计口径。
- 单包源码追踪：NI、Router、NetworkLink 与 CreditLink。
- 性能实验：注入率扫描、饱和、VC 与缓冲资源比较。
- 扩展机制：自定义路由、异构链路宽度和时钟域交叉。

实验过程使用[实验记录模板](../experiments/report_template.md)，保留配置、命令、原始统计与分析。
