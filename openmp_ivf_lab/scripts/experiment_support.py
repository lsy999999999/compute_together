"""Standard-library helpers for CPU budgets, result checks and perf parsing."""

import csv
import json
import math
import os
import platform
import statistics
import subprocess
from pathlib import Path


def text_file(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def cgroup_limits(base=Path('/sys/fs/cgroup'), memberships=None):
    base = Path(base).resolve()
    directories = {base}
    memberships = (text_file('/proc/self/cgroup') or '') if memberships is None else memberships
    for line in memberships.splitlines():
        _, controllers, relative = line.split(':', 2)
        roots = [base] if not controllers else [base / name for name in
                 (controllers, 'cpu', 'cpu,cpuacct', 'cpuset')]
        for root in roots:
            if not root.is_dir():
                continue
            root = root.resolve()
            directories.add(root)
            current = (root / relative.lstrip('/')).resolve()
            # A cgroup namespace may expose only its root, rather than the
            # absolute hierarchy path printed by /proc/self/cgroup.
            if current != root and root not in current.parents:
                continue
            while current == root or root in current.parents:
                if current.is_dir():
                    directories.add(current)
                if current == root:
                    break
                current = current.parent
    files = {}
    capacities = []
    for directory in sorted(directories):
        for name in ('cpu.max', 'cpu.cfs_quota_us', 'cpu.cfs_period_us',
                     'cpuset.cpus', 'cpuset.cpus.effective', 'memory.max'):
            value = text_file(directory / name)
            if value is not None:
                files[str(directory / name)] = value
        maximum = text_file(directory / 'cpu.max')
        if maximum:
            quota, period = maximum.split()[:2]
            if quota != 'max' and float(quota) > 0 and float(period) > 0:
                capacities.append(float(quota) / float(period))
        quota = text_file(directory / 'cpu.cfs_quota_us')
        period = text_file(directory / 'cpu.cfs_period_us')
        if quota and period and float(quota) > 0 and float(period) > 0:
            capacities.append(float(quota) / float(period))
    return dict(membership=memberships, files=files,
                cpu_capacity=min(capacities) if capacities else None)


def resource_plan(cores=None, allow_local=False):
    linux = platform.system() == 'Linux'
    if not linux and not allow_local:
        raise RuntimeError('Formal runs require Linux; --allow-local is for local validation only')
    allowed = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else list(range(os.cpu_count() or 1))
    topology = []
    representatives = {}
    for cpu in allowed:
        root = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        package = text_file(root / 'physical_package_id')
        core = text_file(root / 'core_id')
        key = (package, core) if package is not None and core is not None else ('unknown', cpu)
        representatives.setdefault(key, cpu)
        topology.append(dict(cpu=cpu, socket=package, core=core))
    cgroup = cgroup_limits() if linux else dict(membership='', files={}, cpu_capacity=None)
    maximum = len(representatives)
    if cgroup['cpu_capacity'] is not None:
        maximum = min(maximum, max(1, math.floor(cgroup['cpu_capacity'] + 1e-9)))
    thread_limit = os.environ.get('OMP_THREAD_LIMIT', '')
    if thread_limit.isdecimal() and int(thread_limit) > 0:
        maximum = min(maximum, int(thread_limit))
    requested = cores if cores is not None else (maximum if linux else min(2, maximum))
    if not 1 <= requested <= maximum:
        raise RuntimeError(f'--cores must be between 1 and {maximum} after affinity/quota/thread-limit constraints')
    hypervisor = 'hypervisor' in (text_file('/proc/cpuinfo') or '').split()
    return dict(linux=linux, allowed_cpus=allowed, topology=topology,
                visible_core_representatives=list(representatives.values()),
                selected_cpus=list(representatives.values())[:requested], P=requested,
                cgroup=cgroup, hypervisor_flag=hypervisor,
                budget_units='guest topology cores; host physical allocation unknown' if hypervisor else
                             ('visible core IDs within affinity/quota' if linux else 'local unpinned workers'),
                host_physical_allocation_confirmed=False if hypervisor or not linux else None)


def csv_rows(path):
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, probability):
    """Linear interpolation at (n-1)*p, matching the common type-7 quantile."""
    values = sorted(values)
    if not values:
        return None
    x = (len(values) - 1) * probability
    low = math.floor(x)
    high = math.ceil(x)
    return values[low] + (values[high] - values[low]) * (x - low)


def summarize_measurement(path, batch_path, repeats):
    rows = csv_rows(path)
    if len(rows) != repeats or sorted(int(r['repeat']) for r in rows) != list(range(1, repeats + 1)):
        raise RuntimeError(f'Wrong repeat inventory: {path}')
    if any(r['correctness'] != 'PASS' for r in rows):
        raise RuntimeError(f'Correctness failed: {path}')
    times = [float(r['time_ms']) for r in rows]
    if any(not math.isfinite(t) or t <= 0 for t in times):
        raise RuntimeError(f'Invalid timing: {path}')
    for row in rows:
        if not math.isclose(float(row['qps']), int(row['queries']) * 1000 / float(row['time_ms']), rel_tol=1e-9):
            raise RuntimeError('QPS/time mismatch')
    batches = csv_rows(batch_path)
    by_repeat = {}
    for row in batches:
        by_repeat.setdefault(int(row['repeat']), []).append(row)
    q = int(rows[0]['queries'])
    batch = int(rows[0]['batch'])
    for repeat, measured in enumerate(times, 1):
        samples = by_repeat.get(repeat, [])
        if sum(int(r['query_count']) for r in samples) != q:
            raise RuntimeError('Batch query count does not reconcile')
        if len(samples) != math.ceil(q / batch):
            raise RuntimeError('Wrong number of batches')
        if not math.isclose(sum(float(r['batch_time_ms']) for r in samples), measured,
                            rel_tol=1e-9, abs_tol=1e-8):
            raise RuntimeError('Batch timings do not sum to run timing')
    if len(by_repeat) != repeats:
        raise RuntimeError('Unexpected batch repeat IDs')
    durations = [float(r['batch_time_ms']) for r in batches]
    median = statistics.median(times)
    return dict(min_ms=min(times), median_ms=median, max_ms=max(times),
                qps=q * 1000 / median, recall=float(rows[0]['recall']),
                latency_kind='query' if batch == 1 else 'batch completion',
                sample_p50_ms=percentile(durations, .50), sample_p95_ms=percentile(durations, .95),
                latency_samples=len(durations), correctness='PASS')


def summarize_statistics(prefix):
    prefix = str(prefix)
    queries = csv_rows(prefix + '_queries.csv')
    threads = csv_rows(prefix + '_threads.csv')
    batches = csv_rows(prefix + '_batches.csv')
    lists = csv_rows(prefix + '_lists.csv')
    q_total = sum(int(r['candidates']) for r in queries)
    if q_total != sum(int(r['candidates']) for r in threads):
        raise RuntimeError('Thread work sum differs from query candidates')
    work = {}
    for row in threads:
        work[int(row['thread_id'])] = work.get(int(row['thread_id']), 0) + int(row['candidates'])
    mean = statistics.mean(work.values())
    lengths = [int(r['length']) for r in lists]
    candidates = [int(r['candidates']) for r in queries]
    known_buffers = [sum(int(r[k]) for k in ('local_result_bytes', 'descriptor_bytes', 'exception_bytes'))
                     for r in queries]
    return dict(candidates_total=q_total, candidates_median=statistics.median(candidates),
                candidates_max=max(candidates), list_length_median=statistics.median(lengths),
                list_length_max=max(lengths), work_max_over_mean=max(work.values()) / mean if mean else 0,
                child_tasks_total=sum(int(r['candidate_tasks']) for r in queries),
                parent_tasks_total=sum(int(r['parent_tasks']) for r in queries),
                query_known_buffer_bytes_median=statistics.median(known_buffers),
                query_known_buffer_bytes_max=max(known_buffers),
                query_local_result_bytes_max=max(int(r['local_result_bytes']) for r in queries),
                query_child_heap_upper_bytes_max=max(int(r['child_heap_upper_bound_bytes']) for r in queries),
                merge_query_wall_ms_sum=sum(float(r['merge_query_wall_ms']) for r in queries),
                merge_query_wall_ms_median=statistics.median(float(r['merge_query_wall_ms']) for r in queries),
                select_query_wall_ms_sum=sum(float(r['select_query_wall_ms']) for r in queries),
                taskgroup_query_wall_ms_sum=sum(float(r['taskgroup_query_wall_ms']) for r in queries),
                actual_threads_min=min(int(r['actual_threads']) for r in batches),
                actual_threads_max=max(int(r['actual_threads']) for r in batches),
                active_candidate_threads_max=max(int(r['active_candidate_threads']) for r in batches))


def parse_perf(path, total_queries, total_candidates):
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        fields = line.split(';')
        if len(fields) < 3 or not fields[2].strip():
            continue
        raw = fields[0].strip()
        try:
            value = float(raw.replace(',', ''))
        except ValueError:
            value = None
        rows.append(dict(event=fields[2].strip(), unit=fields[1].strip(), raw_count=raw,
                         status='measured' if value is not None and math.isfinite(value) else 'unavailable',
                         count=value if value is not None and math.isfinite(value) else None,
                         per_query=value / total_queries if value is not None and math.isfinite(value) else None,
                         per_candidate=value / total_candidates if value is not None and math.isfinite(value)
                                       and total_candidates else None,
                         runtime_raw=fields[3].strip() if len(fields) > 3 else '',
                         running_percent_raw=fields[4].strip() if len(fields) > 4 else ''))
    return rows
