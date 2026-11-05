# 第二阶段本机验证记录

验证日期：2026-11-05。本文件记录开发验证范围，正式 Linux 性能数据由服务器运行后产生。

## 已完成

- Apple Clang 21 / Homebrew libomp：优化构建、公共输入与 Top-k 测试通过。
- 学生实现测试：2,905 个普通搜索配置及 48 个独立统计配置通过；覆盖 serial、std、两种 OpenMP 策略和 SIMD。
- CLI：原有 21 项检查通过；新增 12 个统计与查询重排组合、batch 样本核对、FIFO 确认协议、预热排除和超时检查通过。
- CPU 预算工具：SMT、配额、虚拟拓扑、cgroup v2 祖先/命名空间根、cgroup v1 符号链接夹具通过。
- GCC 16：学生实现测试及新增 CLI 集成测试通过。
- AddressSanitizer / UndefinedBehaviorSanitizer：学生实现测试及最新 CLI 集成测试通过。
- 优化构建的 `make vector-report` 已生成向量化证据。O1 sanitizer 构建的未向量化警告不作为优化构建的结论。

## 完整真实数据上的流程验证

使用本机完整 SIFT1M（N=1,000,000，d=128，4,096 个列表）执行：

```bash
python3 scripts/run_experiments.py --data-dir dataset \
  --out results/local_pipeline_validation_20261105 \
  --cores 2 --quick --allow-local --no-build --skip-perf
```

P=2、Q=8、固定大 batch=8。24 个不同配置、48 次正式样式的快速重复及各配置独立统计全部通过。组表行数为 A=8、B=6、C=4、D=3、E=8、std=2；相同配置按 run_id 复用。输出保留在本机，未随源码上传。

这是两次重复的 macOS 流程验证，不能作为十次重复的 Linux 性能实验。此次完整流程之后的修改涉及 FIFO 确认分隔符、配额测试接口、文档和回退错误处理，已用对应集成测试验证。

## 服务器仍需执行

```bash
bash scripts/run_all.sh /var/dataset
```

真实 Linux CPU 绑定、服务器编译器和 OpenMP 运行时、实际 perf 权限/事件/FIFO 控制均待服务器验证。模拟 FIFO 控制器只验证协议，不提供真实性能计数证据。服务器无法采集 perf 时，保留原始错误并单独记录 GNU time 的整个进程统计。

服务器历史 pilot 结果保持原样；本次脚本在新的 `results/server_full_时间戳/` 中保存输出。报告分析和学生本人撰写的个人反思尚未完成。
