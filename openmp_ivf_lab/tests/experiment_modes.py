#!/usr/bin/env python3
"""Integration checks for diagnostics, query reorder, latency samples and perf FIFO control."""

import argparse
import csv
import math
import os
import select
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from smoke_cli import fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from experiment_support import (cgroup_limits, csv_rows, parse_perf, percentile, resource_plan,
                                summarize_measurement, summarize_statistics)


def invoke(binary, data, arguments, good=True):
    proc = subprocess.run([str(binary), *data, *arguments], text=True, capture_output=True, timeout=30)
    if good and (proc.returncode or 'correctness=PASS' not in proc.stdout):
        raise RuntimeError(proc.stdout + proc.stderr)
    return proc


def run(binary):
    with tempfile.TemporaryDirectory(prefix='ivf_experiment_tests_') as tmp:
        root = Path(tmp)
        fixtures(root)
        data = ['--base', str(root / 'sift_base.fbin'), '--queries-file', str(root / 'sift_query.fbin'),
                '--centroids', str(root / 'centroid_4096.fvecs'), '--cluster-ids', str(root / 'cluster_id_4096.ivecs'),
                '--gt', str(root / 'gt.ibin'), '--queries', '13', '--k', '10', '--nprobe', '3', '--grain', '8']
        reference_pool = None
        reference_recall = None
        for strategy in ('serial', 'std', 'omp1', 'omp2'):
            for order in ('original', 'candidates-asc', 'candidates-desc'):
                prefix = root / f'{strategy}_{order}'
                order_csv = root / f'{strategy}_{order}_order.csv'
                proc = invoke(binary, data, ['--only', strategy, '--simd', 'on' if strategy.startswith('omp') else 'off',
                              '--threads', '4', '--batch', '5', '--query-order', order,
                              '--mode', 'stats', '--stats-prefix', str(prefix), '--order-csv', str(order_csv)])
                assert 'statistics=PASS' in proc.stdout
                stats = summarize_statistics(prefix)
                assert stats['actual_threads_max'] >= 1
                rows = csv_rows(order_csv)
                assert sorted(int(r['original_query_id']) for r in rows) == list(range(13))
                pool = {int(r['original_query_id']): int(r['candidates']) for r in rows}
                if reference_pool is None: reference_pool = pool
                assert pool == reference_pool
                c = [int(r['candidates']) for r in rows]
                if order != 'original': assert c == sorted(c, reverse=order.endswith('desc'))
                recall = float(proc.stdout.rsplit('=', 1)[1])
                if reference_recall is None: reference_recall = recall
                assert recall == reference_recall
        repeats = root / 'repeats.csv'
        batches = root / 'batches.csv'
        invoke(binary, data, ['--only', 'omp2', '--threads', '4', '--batch', '5', '--warmup', '1',
               '--repeats', '2', '--csv', str(repeats), '--batches-csv', str(batches)])
        metrics = summarize_measurement(repeats, batches, 2)
        assert metrics['latency_kind'] == 'batch completion' and metrics['latency_samples'] == 6
        assert [int(r['query_count']) for r in csv_rows(batches)] == [5, 5, 3] * 2
        assert math.isclose(percentile([1., 2., 100.], .95), 90.2)

        # A test controller validates protocol placement/acknowledgements, not HW counters.
        control, ack = root / 'control.fifo', root / 'ack.fifo'
        os.mkfifo(control)
        os.mkfifo(ack)
        control_fd = os.open(control, os.O_RDWR | os.O_NONBLOCK)
        ack_fd = os.open(ack, os.O_RDWR | os.O_NONBLOCK)
        commands = []
        stop = threading.Event()
        def controller():
            buffered = b''
            while not stop.is_set():
                ready, _, _ = select.select([control_fd], [], [], .1)
                if not ready: continue
                buffered += os.read(control_fd, 1024)
                while b'\n' in buffered:
                    line, buffered = buffered.split(b'\n', 1)
                    commands.append(line.decode())
                    os.write(ack_fd, b'ack\0' if len(commands) % 2 else b'ack\n\0')
        thread = threading.Thread(target=controller, daemon=True)
        thread.start()
        control_log = root / 'control.csv'
        try:
            invoke(binary, data, ['--only', 'std', '--threads', '2', '--batch', '5', '--warmup', '2',
                   '--repeats', '3', '--perf-control', str(control), '--perf-ack', str(ack),
                   '--perf-log', str(control_log), '--perf-timeout-ms', '2000'])
        finally:
            stop.set()
            thread.join(timeout=2)
            os.close(control_fd)
            os.close(ack_fd)
        assert commands == ['enable', 'disable'] * 3  # No warmup commands.
        assert [r['command'] for r in csv_rows(control_log)] == commands
        timed_out = invoke(binary, data, ['--only', 'omp2', '--warmup', '1', '--repeats', '1',
                           '--perf-control', str(control), '--perf-ack', str(ack),
                           '--perf-timeout-ms', '100'], good=False)
        assert timed_out.returncode != 0 and 'acknowledgement timeout' in timed_out.stderr

        perf_file = root / 'perf.csv'
        perf_file.write_text('1000;;cycles;100000;52.00\n<not supported>;;cache-misses;0;100.00\n')
        counters = parse_perf(perf_file, 10, 100)
        assert counters[0]['per_query'] == 100 and counters[0]['per_candidate'] == 10
        assert counters[0]['running_percent_raw'] == '52.00'
        assert counters[1]['count'] is None and counters[1]['status'] == 'unavailable'

        cgroups = root / 'cgroups'
        child = cgroups / 'a' / 'b'
        child.mkdir(parents=True)
        (cgroups / 'cpu.max').write_text('max 100000')
        (cgroups / 'a' / 'cpu.max').write_text('250000 100000')
        (child / 'cpu.max').write_text('400000 100000')
        assert cgroup_limits(cgroups, '0::/a/b')['cpu_capacity'] == 2.5
        (cgroups / 'cpu.max').write_text('100000 100000')
        assert cgroup_limits(cgroups, '0::/outside/namespace')['cpu_capacity'] == 1
        (cgroups / 'cpu.max').unlink()
        v1 = cgroups / 'cpu,cpuacct' / 'job'
        v1.mkdir(parents=True)
        (cgroups / 'cpu').symlink_to('cpu,cpuacct', target_is_directory=True)
        (v1 / 'cpu.cfs_quota_us').write_text('200000')
        (v1 / 'cpu.cfs_period_us').write_text('100000')
        assert cgroup_limits(cgroups, '1:cpu:/job')['cpu_capacity'] == 2

        def fake_text(path):
            path = str(path)
            if path == '/proc/cpuinfo': return 'flags : hypervisor'
            if path.endswith('physical_package_id'): return '0'
            if path.endswith('core_id'): return str(int(path.split('/cpu')[-1].split('/')[0]) // 2)
            return None
        with patch('experiment_support.platform.system', return_value='Linux'), \
             patch('experiment_support.os.sched_getaffinity', return_value=set(range(6)), create=True), \
             patch('experiment_support.text_file', side_effect=fake_text), \
             patch('experiment_support.cgroup_limits', return_value={'membership':'', 'files':{}, 'cpu_capacity':2.5}), \
             patch.dict(os.environ, {'OMP_THREAD_LIMIT': ''}):
            plan = resource_plan()
            assert plan['P'] == 2 and plan['selected_cpus'] == [0, 2]
            assert plan['hypervisor_flag'] and not plan['host_physical_allocation_confirmed']
            try:
                resource_plan(3)
            except RuntimeError:
                pass
            else:
                raise RuntimeError('CPU quota constraint was ignored')
    print('PASS: 12 diagnostic/reorder CLI cases; batch sample reconciliation; perf ack/warmup/timeout; CPU quota/SMT and missing-counter handling')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'ivf_lab')
    run(parser.parse_args().binary.resolve())
