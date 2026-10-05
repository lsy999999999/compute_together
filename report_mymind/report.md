观察到了从 4 到 8 线程明显的扩展效率下降，但仅凭当前实验无法区分其主要来源究竟是 skew-induced load imbalance、OpenMP overhead、memory-bandwidth saturation，还是 Apple Silicon 异构核心调度

在默认 skewed CSR 矩阵上，OpenMP static 调度在 2 个和 4 个线程时取得了明显加速，分别达到约 1.92× 和 3.04×；然而扩展到 8 个线程后，加速比仅提高至 3.53×，并行效率由 4 线程时的 76.0% 降至 44.1%。此外，单线程 OpenMP 版本慢于纯串行实现，表明对于亚毫秒级 SpMV kernel，并行运行时开销不可忽略。4 到 8 线程之间明显的扩展效率下降表明系统开始受到新的瓶颈限制，但当前数据尚不能区分负载不均衡、内存带宽和并行运行时开销的贡献，后续将通过 dynamic scheduling 与不同矩阵 skew 程度的对照实验进一步验证。


> 对于当前 skewed CSR SpMV，尽管 dynamic scheduling 理论上能够缓解长短行造成的负载不均衡，但细粒度 `schedule(dynamic,1)` 引入了显著的运行时调度开销。由于大多数行仅包含 32 个非零元素，单行计算时间较短，任务调度成本相对于实际计算成本过高。因此 dynamic(1) 在 4 和 8 线程下均慢于 static，并且在 8 线程下退化更加明显。
