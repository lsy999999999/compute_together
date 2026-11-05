#!/usr/bin/env python3
"""Build, validate and run the assignment's A-E experiments on one CPU budget."""

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from experiment_support import (csv_rows, parse_perf, resource_plan, summarize_measurement,
                                summarize_statistics, text_file, write_csv)
from validate_real_data import environment, inspect_data

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Configuration:
    strategy: str
    threads: int
    batch: int
    nprobe: int = 8
    grain: int = 1024
    simd: str = 'off'
    query_order: str = 'original'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class Suite:
    def __init__(self, args):
        self.args = args
        self.output = args.out.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.plan = resource_plan(args.cores, args.allow_local)
        self.P = self.plan['P']
        self.Q = max(args.queries if args.queries is not None else (8 if args.quick else 128), 4 * self.P)
        if not 1 <= self.Q <= 10000:
            raise RuntimeError('Q must be <=10000 and >=4P')
        self.large_batch = 4 * self.P
        self.repeats = 2 if args.quick else 10
        self.dataset, self.data_args = inspect_data(args.data_dir.resolve())
        self.binary = ROOT / 'ivf_lab'
        self.env = os.environ.copy()
        self.env.update(LC_ALL='C', OMP_DYNAMIC='FALSE', OMP_WAIT_POLICY=args.wait_policy.upper(),
                        OMP_MAX_ACTIVE_LEVELS='1', OMP_NUM_THREADS=str(self.P))
        self.prefix = []
        self.pin_args = []
        if self.plan['linux']:
            taskset = shutil.which('taskset')
            if not taskset:
                raise RuntimeError('taskset (util-linux) is required for a common Linux CPU set')
            cpus = ','.join(map(str, self.plan['selected_cpus']))
            self.prefix = [taskset, '--cpu-list', cpus]
            self.pin_args = ['--pin-cpus', cpus]
            self.env.update(OMP_PROC_BIND='close', OMP_PLACES=','.join('{%d}' % c for c in self.plan['selected_cpus']))
        else:
            self.env['OMP_PROC_BIND'] = 'FALSE'
            self.env.pop('OMP_PLACES', None)
        self.runs = {}
        self.candidate_pools = {}
        self.recalls = {}
        self.groups = {}
        self.manifest = dict(started_utc=stamp(), status='running',
                             profile='quick_validation' if args.quick else
                                     ('formal_experiment' if self.plan['linux'] else 'local_validation'),
                             environment=environment(), resources=self.plan, Q=self.Q,
                             large_batch=self.large_batch, warmup=1, repeats=self.repeats,
                             runtime_environment={k: self.env.get(k) for k in
                             ('OMP_DYNAMIC', 'OMP_NUM_THREADS', 'OMP_PLACES', 'OMP_PROC_BIND',
                              'OMP_WAIT_POLICY', 'OMP_MAX_ACTIVE_LEVELS', 'OMP_THREAD_LIMIT')},
                             dataset=self.dataset, build_requested=not args.no_build,
                             notes=['Per-query phase wall intervals can overlap; their sum is not batch wall time.',
                                    'Known query buffers exclude runtime task objects, center temporaries and parent heaps.',
                                    'Counter runs use separate processes from A-E timing.',
                                    'A virtual-machine CPU budget does not establish host physical-core allocation.'])
        save_json(self.output / 'manifest.json', self.manifest)
        (self.output / 'dataset.sha256').write_text(''.join(
            f"{value['sha256']}  {name}\n" for name, value in self.dataset.items()))

    def invoke(self, command, log, check=True, env=None, timeout=1800):
        log = Path(log)
        try:
            proc = subprocess.run(command, cwd=ROOT, env=self.env if env is None else env,
                                  text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or ''
            stderr = error.stderr or ''
            if isinstance(stdout, bytes): stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes): stderr = stderr.decode(errors='replace')
            log.write_text(json.dumps(command) + '\n' + stdout + stderr + '\nTIMEOUT\n')
            raise RuntimeError(f'Command timed out; see {log}') from error
        except OSError as error:
            log.write_text(json.dumps(command) + '\n' + str(error) + '\n')
            if check:
                raise RuntimeError(f'Cannot run command; see {log}') from error
            return None
        log.write_text(json.dumps(command) + '\n' + proc.stdout + proc.stderr, encoding='utf-8')
        if check and proc.returncode:
            raise RuntimeError(f'Command exited {proc.returncode}; see {log}')
        return proc

    def build(self):
        if not self.args.no_build:
            print('Building and checking all implementations', flush=True)
            self.invoke(['make', 'clean'], self.output / 'build_clean.log')
            self.invoke(['make', '-j4'], self.output / 'build.log')
            self.invoke(['make', 'test'], self.output / 'unit_tests.log')
            self.invoke(['make', 'smoke'], self.output / 'cli_tests.log')
            self.invoke(['make', 'vector-report'], self.output / 'vector_build.log')
            shutil.copy2(ROOT / 'build/vectorization.txt', self.output / 'vectorization.txt')
        if not self.binary.is_file():
            raise RuntimeError('ivf_lab is missing; run make')
        self.invoke(['git', 'rev-parse', 'HEAD'], self.output / 'source_commit.log', check=False)
        self.invoke(['git', 'diff', '--name-only', '--', '*.cpp', '*.h', 'Makefile', 'scripts', 'tests'],
                    self.output / 'source_changes.log', check=False)
        self.invoke(['ldd', str(self.binary)], self.output / 'runtime_libraries.log', check=False)
        self.invoke(['uname', '-a'], self.output / 'uname.log', check=False)
        self.invoke(['lscpu', '-e=CPU,CORE,SOCKET,NODE,ONLINE'], self.output / 'cpu_topology.log', check=False)
        self.invoke(['free', '-h'], self.output / 'memory.log', check=False)
        self.invoke(['perf', '--version'], self.output / 'perf_version.log', check=False)
        self.invoke(['perf', 'list', '--raw-dump'], self.output / 'perf_events.log', check=False)
        self.manifest['perf_event_paranoid'] = text_file('/proc/sys/kernel/perf_event_paranoid')
        self.manifest['binary_sha256'] = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        sources = [*ROOT.glob('ivf*.cpp'), *ROOT.glob('ivf*.h'), ROOT / 'Makefile',
                   *ROOT.glob('scripts/*.py'), *ROOT.glob('scripts/*.sh')]
        self.manifest['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in sorted(sources)}
        save_json(self.output / 'manifest.json', self.manifest)

    def command(self, config):
        return [*self.prefix, str(self.binary), *self.data_args, *self.pin_args,
                '--only', config.strategy, '--threads', str(config.threads),
                '--queries', str(self.Q), '--batch', str(config.batch), '--k', '10',
                '--nprobe', str(config.nprobe), '--grain', str(config.grain),
                '--simd', config.simd, '--query-order', config.query_order]

    def measure(self, config, group):
        if config not in self.runs:
            run_id = f'run_{len(self.runs) + 1:03d}'
            directory = self.output / run_id
            directory.mkdir()
            print(f'[{group}] {run_id}: {config}', flush=True)
            save_json(directory / 'configuration.json', asdict(config))
            raw = directory / 'repeats.csv'
            batch_raw = directory / 'batch_samples.csv'
            proc = self.invoke([*self.command(config), '--warmup', '1', '--repeats', str(self.repeats),
                                '--csv', str(raw), '--batches-csv', str(batch_raw)], directory / 'bench.log')
            if 'correctness=PASS' not in proc.stdout:
                raise RuntimeError(f'Missing correctness result: {directory}')
            measured = summarize_measurement(raw, batch_raw, self.repeats)
            stats_prefix = directory / 'diagnostics'
            order_path = directory / 'query_order.csv'
            proc = self.invoke([*self.command(config), '--mode', 'stats', '--stats-prefix', str(stats_prefix),
                                '--order-csv', str(order_path)], directory / 'diagnostics.log')
            if 'correctness=PASS' not in proc.stdout or 'statistics=PASS' not in proc.stdout:
                raise RuntimeError(f'Missing diagnostic result: {directory}')
            stats = summarize_statistics(stats_prefix)
            if config.strategy.startswith('omp') and stats['actual_threads_max'] != config.threads:
                raise RuntimeError(f'Requested OpenMP team was limited; see {directory}')
            orders = csv_rows(order_path)
            if sorted(int(r['original_query_id']) for r in orders) != list(range(self.Q)):
                raise RuntimeError('Query order lost or repeated a query')
            c = [int(r['candidates']) for r in orders]
            if config.query_order != 'original' and c != sorted(c, reverse=config.query_order.endswith('desc')):
                raise RuntimeError('Candidate order is not sorted')
            pool = {int(r['original_query_id']): int(r['candidates']) for r in orders}
            key = (config.nprobe, self.Q)
            if key in self.candidate_pools and self.candidate_pools[key] != pool:
                raise RuntimeError('Candidate pool changed between strategies or orders')
            self.candidate_pools[key] = pool
            if key in self.recalls and not math.isclose(self.recalls[key], measured['recall'], abs_tol=1e-12):
                raise RuntimeError('Recall changed after reordering or strategy change')
            self.recalls[key] = measured['recall']
            row = dict(run_id=run_id, **asdict(config), Q=self.Q, k=10, **measured, **stats)
            self.runs[config] = row
            save_json(directory / 'summary.json', row)
        return dict(group=group, **self.runs[config])

    def experiments(self):
        baseline = {}
        for batch in (1, self.large_batch):
            baseline[batch] = self.measure(Configuration('serial', 1, batch), 'baseline')
        levels = []
        p = 1
        while p <= self.P:
            levels.append(p)
            p *= 2
        if self.P not in levels: levels.append(self.P)
        a = []
        for batch in (1, self.large_batch):
            for p in levels:
                for strategy in ('omp1', 'omp2'):
                    row = self.measure(Configuration(strategy, p, batch), 'A')
                    speedup = baseline[batch]['median_ms'] / row['median_ms']
                    a.append(dict(**row, serial_baseline_run=baseline[batch]['run_id'],
                                  speedup=speedup, efficiency=speedup / p))
        self.groups['A_scaling'] = a
        self.groups['B_order'] = [self.measure(Configuration(s, self.P, self.large_batch, query_order=o), 'B')
                                  for s in ('omp1', 'omp2')
                                  for o in ('original', 'candidates-asc', 'candidates-desc')]
        self.groups['C_grain'] = [self.measure(Configuration('omp2', self.P, self.large_batch, grain=g), 'C')
                                  for g in (64, 256, 1024, 4096)]
        self.groups['D_nprobe'] = [self.measure(Configuration('omp2', self.P, self.large_batch, nprobe=n), 'D')
                                   for n in (1, 8, 32)]
        e = []
        for p in sorted({1, self.P}):
            for strategy in ('omp1', 'omp2'):
                off = self.measure(Configuration(strategy, p, self.large_batch), 'E')
                on = self.measure(Configuration(strategy, p, self.large_batch, simd='on'), 'E')
                for row in (off, on):
                    e.append(dict(**row, off_baseline_run=off['run_id'],
                                  simd_speedup=off['median_ms'] / row['median_ms']))
        self.groups['E_simd'] = e
        std = self.measure(Configuration('std', self.P, self.large_batch), 'std_compare')
        omp = self.measure(Configuration('omp1', self.P, self.large_batch), 'std_compare')
        self.groups['std_compare'] = [dict(**row, serial_baseline_run=baseline[self.large_batch]['run_id'],
                                         speedup=baseline[self.large_batch]['median_ms'] / row['median_ms'])
                                      for row in (std, omp)]
        self.groups['baseline'] = list(baseline.values())
        for name, rows in self.groups.items():
            write_csv(self.output / f'{name}.csv', rows)
        write_csv(self.output / 'all_runs.csv', list(self.runs.values()))

    def perf(self):
        results = []
        if self.args.skip_perf or not self.plan['linux']:
            save_json(self.output / 'perf_status.json', dict(status='skipped',
                      reason='--skip-perf' if self.args.skip_perf else 'local non-Linux validation'))
            return 'skipped'
        directory = self.output / 'perf'
        directory.mkdir()
        hardware = 'task-clock,cycles,instructions,cache-misses,context-switches,cpu-migrations'
        software = 'task-clock,context-switches,cpu-migrations'
        for strategy in ('serial', 'omp2', 'std'):
            config = Configuration(strategy, 1 if strategy == 'serial' else self.P, self.large_batch)
            measured = self.measure(config, 'perf_reference')
            target = directory / strategy
            target.mkdir()
            captured = False
            for label, events in (('hardware', hardware), ('software', software)):
                attempt = target / label
                attempt.mkdir()
                if not shutil.which('perf'):
                    save_json(attempt / 'status.json', dict(status='unavailable', reason='perf is not installed'))
                    break
                print(f'[perf] {strategy}: {label} events', flush=True)
                counts = attempt / 'counters.csv'
                control_log = attempt / 'control.csv'
                program_csv = attempt / 'program.csv'
                with tempfile.TemporaryDirectory(prefix='ivf_perf_') as tmp:
                    control = Path(tmp) / 'control.fifo'
                    ack = Path(tmp) / 'ack.fifo'
                    os.mkfifo(control)
                    os.mkfifo(ack)
                    command = ['perf', 'stat', '--delay=-1', f'--control=fifo:{control},{ack}',
                               '-x', ';', '-o', str(counts), '-e', events, '--',
                               *self.command(config), '--warmup', '1', '--repeats', str(self.repeats),
                               '--csv', str(program_csv), '--perf-control', str(control), '--perf-ack', str(ack),
                               '--perf-log', str(control_log)]
                    proc = self.invoke(command, attempt / 'perf.log', check=False)
                details = dict(returncode=proc.returncode if proc else None,
                               inheritance='perf stat default inheritance; no --no-inherit option',
                               scope='enabled after warmup; disabled before each result check; loading excluded',
                               note='Counts include small timing/control overhead inside the enabled region.',
                               worker_evidence=str((self.output / measured['run_id'] / 'diagnostics_threads.csv').relative_to(self.output)))
                rows = parse_perf(counts, self.Q * self.repeats,
                                  measured['candidates_total'] * self.repeats) if counts.exists() else []
                selected = set(events.split(','))
                valid = {r['event'].split(':')[0] for r in rows if r['status'] == 'measured'
                         and r['event'].split(':')[0] in selected}
                if proc and proc.returncode == 0 and control_log.exists() and program_csv.exists() and len(valid) >= 2:
                    controls = csv_rows(control_log)
                    if [r['command'] for r in controls] != ['enable', 'disable'] * self.repeats:
                        raise RuntimeError('perf acknowledgements did not cover exactly the formal repeats')
                    program = csv_rows(program_csv)
                    if len(program) != self.repeats or any(r['correctness'] != 'PASS' for r in program):
                        raise RuntimeError('perf workload correctness/repeats failed')
                    write_csv(attempt / 'normalized_counters.csv', rows)
                    details.update(status='measured', measured_events=sorted(valid),
                                   total_queries=self.Q * self.repeats,
                                   total_candidates=measured['candidates_total'] * self.repeats,
                                   acknowledged_pairs=self.repeats)
                    captured = True
                else:
                    details.update(status='unavailable_or_incomplete', parsed_counters=rows)
                save_json(attempt / 'status.json', details)
                if captured:
                    results.append(dict(strategy=strategy, tool='perf stat', status='measured', attempt=label))
                    break
            if not captured:
                # GNU time observes the entire process. Keep it separate from
                # retrieval-only CSV timings and never fill missing HW counters.
                fallback = target / 'time_fallback'
                fallback.mkdir()
                print(f'[perf fallback] {strategy}: GNU time for whole process', flush=True)
                command = ['/usr/bin/time', '-v', '-o', str(fallback / 'time_verbose.txt'),
                           *self.command(config), '--warmup', '1', '--repeats', str(self.repeats),
                           '--csv', str(fallback / 'program.csv')]
                proc = self.invoke(command, fallback / 'time.log', check=False)
                if proc and proc.returncode and 'error:' in (proc.stdout + proc.stderr):
                    raise RuntimeError(f'Fallback retrieval workload failed; see {fallback}')
                status = 'whole_process_only' if proc and proc.returncode == 0 else 'unavailable'
                if proc and proc.returncode == 0 and 'correctness=PASS' not in proc.stdout:
                    raise RuntimeError('Fallback workload did not pass correctness')
                save_json(fallback / 'status.json', dict(status=status,
                          includes='loading, reference, warmup, checks, retrieval, thread management and process lifecycle',
                          hardware_counters='not measured; no substituted hardware values'))
                results.append(dict(strategy=strategy, tool='/usr/bin/time -v', status=status, attempt='fallback'))
        write_csv(directory / 'status.csv', results)
        status = 'measured' if all(r['status'] == 'measured' for r in results) else 'fallback_or_unavailable'
        save_json(self.output / 'perf_status.json', dict(status=status, strategies=results))
        return status

    def finish(self, perf_status):
        self.manifest.update(status='PASS', finished_utc=stamp(), unique_measured_configurations=len(self.runs),
                             groups=list(self.groups), perf_status=perf_status,
                             submission_ready=False,
                             remaining='Interpret results, verify VM/host CPU allocation, write report and personal reflection')
        save_json(self.output / 'manifest.json', self.manifest)
        lines = ['# A-E 实验运行记录', '',
                 f"运行类型：{self.manifest['profile']}。CPU 预算 P={self.P}；单位：{self.plan['budget_units']}。",
                 f'Q={self.Q}，大 batch={self.large_batch}=4P；预热 1 次，正式重复 {self.repeats} 次。', '',
                 f'完成 {len(self.runs)} 个不同计时配置，逐次完整结果检查及独立统计运行均通过。',
                 f'perf 状态：{perf_status}。详情见 perf_status.json 和原始工具输出。', '',
                 'A_scaling.csv 包含相对同 batch 串行基线的加速比和效率；主表使用公共标量距离。',
                 'B_order.csv 使用同一查询池并同步重排 ground truth；线程工作量另跑统计采集。',
                 'C_grain.csv 包含任务数、已计入的查询缓冲区和阶段诊断；已知缓冲区不是进程峰值内存。',
                 'D_nprobe.csv 包含候选数、Recall 与 QPS；E_simd.csv 单独比较固定线程数的距离开关。',
                 'std_compare.csv 比较同一 CPU 集合和显式线程绑定下的 std::thread 与查询级 OpenMP。', '',
                 'batch=1 的 sample_p50_ms/sample_p95_ms 为查询延迟；batch>1 时为 batch 完成时间。',
                 '分位数使用 (n-1)*p 线性插值，只使用正式重复的逐 batch 样本。',
                 '统计与计时分开。各查询的阶段墙钟区间可以重叠，不能把它们相加当作 batch 墙钟时间。',
                 '不同组复用完全相同配置的同一次测量；run_id 指向对应原始记录。', '',
                 '本记录由程序生成。实验分析与报告仍需核实，个人心路历程由学生本人撰写。', '']
        (self.output / 'RUN_NOTES.md').write_text('\n'.join(lines), encoding='utf-8')
        print(f'COMPLETE: {self.output}\nCPU budget P={self.P}; Q={self.Q}; batch={self.large_batch}; perf={perf_status}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('/var/dataset'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cores', type=int, help='CPU budget; defaults to affinity/core/quota constraints')
    parser.add_argument('--queries', type=int, help='Minimum Q; automatically raised to at least 4P')
    parser.add_argument('--wait-policy', choices=('passive', 'active'), default='passive')
    parser.add_argument('--quick', action='store_true', help='Two repeats for pipeline validation, not submission')
    parser.add_argument('--allow-local', action='store_true', help='Allow unpinned macOS validation')
    parser.add_argument('--no-build', action='store_true', help='Use current binary; build flags not recaptured')
    parser.add_argument('--skip-perf', action='store_true')
    args = parser.parse_args()
    if args.queries is not None and args.queries < 1:
        parser.error('--queries must be positive')
    suite = None
    try:
        suite = Suite(args)
        suite.build()
        suite.experiments()
        suite.finish(suite.perf())
    except BaseException as error:
        if suite is not None:
            suite.manifest.update(status='FAILED', finished_utc=stamp(), error=str(error))
            save_json(suite.output / 'manifest.json', suite.manifest)
        raise


if __name__ == '__main__':
    main()
