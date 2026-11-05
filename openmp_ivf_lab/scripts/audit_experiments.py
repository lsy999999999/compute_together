#!/usr/bin/env python3
"""Independently reconcile downloaded experiment records without changing them."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def rows(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-8, abs_tol=1e-8), (a, b)


def quantile(values, p):
    values = sorted(values)
    x = (len(values) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return values[lo] + (x - lo) * (values[hi] - values[lo])


def audit(source, output):
    manifest = json.loads((source / 'manifest.json').read_text())
    assert manifest['status'] == 'PASS' and manifest['profile'] == 'formal_experiment'
    assert manifest['warmup'] >= 1 and manifest['repeats'] == 10
    P, Q = manifest['resources']['P'], manifest['Q']
    assert manifest['large_batch'] == 4 * P and Q >= 4 * P
    summary = rows(source / 'all_runs.csv')
    assert len(summary) == manifest['unique_measured_configurations']
    assert len({r['run_id'] for r in summary}) == len(summary)
    assert len(list(source.glob('run_*'))) == len(summary)
    by_id = {r['run_id']: r for r in summary}
    candidate_pools, recalls = {}, {}
    audit_rows, repeat_count, samples_count, cpu_samples = [], 0, 0, 0
    for r in summary:
        directory = source / r['run_id']
        config = json.loads((directory / 'configuration.json').read_text())
        saved = json.loads((directory / 'summary.json').read_text())
        for k, v in config.items():
            assert str(v) == r[k], (r['run_id'], k)
        for k, v in saved.items():
            if isinstance(v, (int, float)): close(v, r[k])
            else: assert str(v) == r[k]
        repeats = rows(directory / 'repeats.csv')
        batches = rows(directory / 'batch_samples.csv')
        assert len(repeats) == 10
        assert sorted(int(x['repeat']) for x in repeats) == list(range(1, 11))
        by_repeat = defaultdict(list)
        for x in batches: by_repeat[int(x['repeat'])].append(x)
        durations = []
        for x in repeats:
            assert x['correctness'] == 'PASS'
            for key in ('strategy', 'threads', 'batch', 'nprobe', 'grain', 'simd', 'query_order'):
                assert x[key] == r[key]
            assert int(x['queries']) == Q
            t = float(x['time_ms'])
            assert math.isfinite(t) and t > 0
            close(x['qps'], Q * 1000 / t)
            close(x['recall'], r['recall'])
            batch = by_repeat[int(x['repeat'])]
            assert len(batch) == math.ceil(Q / int(r['batch']))
            assert sum(int(y['query_count']) for y in batch) == Q
            close(sum(float(y['batch_time_ms']) for y in batch), t)
            durations.append(t)
        close(r['median_ms'], statistics.median(durations))
        close(r['min_ms'], min(durations)); close(r['max_ms'], max(durations))
        close(r['qps'], Q * 1000 / statistics.median(durations))
        batch_times = [float(x['batch_time_ms']) for x in batches]
        close(r['sample_p50_ms'], quantile(batch_times, .5))
        close(r['sample_p95_ms'], quantile(batch_times, .95))
        assert int(r['latency_samples']) == len(batch_times)
        queries = rows(directory / 'diagnostics_queries.csv')
        workers = rows(directory / 'diagnostics_threads.csv')
        dbatches = rows(directory / 'diagnostics_batches.csv')
        lists = rows(directory / 'diagnostics_lists.csv')
        order = rows(directory / 'query_order.csv')
        assert len(queries) == len(order) == Q
        assert len(lists) == 4096 and sum(int(x['length']) for x in lists) == 1000000
        assert sorted(int(x['original_query_id']) for x in order) == list(range(Q))
        pool = {int(x['original_query_id']): int(x['candidates']) for x in order}
        key = int(r['nprobe'])
        if key in candidate_pools: assert candidate_pools[key] == pool
        candidate_pools[key] = pool
        if key in recalls: close(recalls[key], r['recall'])
        recalls[key] = float(r['recall'])
        if r['query_order'] != 'original':
            counts = [int(x['candidates']) for x in order]
            assert counts == sorted(counts, reverse=r['query_order'].endswith('desc'))
        for x in queries: assert pool[int(x['original_query_id'])] == int(x['candidates'])
        total = sum(pool.values())
        close(r['candidates_total'], total)
        for batch in dbatches:
            b = batch['batch_index']
            qs = [x for x in queries if x['batch_index'] == b]
            ws = [x for x in workers if x['batch_index'] == b]
            assert len(qs) == int(batch['query_count'])
            assert len(ws) == int(r['threads'])
            assert sum(int(x['candidates']) for x in qs) == sum(int(x['candidates']) for x in ws) == int(batch['candidates'])
            assert sum(int(x['candidate_tasks']) for x in qs) == sum(int(x['candidate_tasks']) for x in ws) == int(batch['child_tasks'])
            assert sum(int(x['completed_queries']) for x in ws) == len(qs)
            if r['strategy'].startswith('omp'): assert int(batch['actual_threads']) == int(r['threads'])
            for x in ws:
                for field in ('first_cpu', 'last_cpu'):
                    cpu = int(x[field])
                    if cpu >= 0:
                        expected = manifest['resources']['selected_cpus'][int(x['thread_id'])]
                        assert cpu == expected, (r['run_id'], x)
                        cpu_samples += 1
        work = defaultdict(int)
        for x in workers: work[int(x['thread_id'])] += int(x['candidates'])
        close(r['work_max_over_mean'], max(work.values()) / statistics.mean(work.values()))
        close(r['child_tasks_total'], sum(int(x['candidate_tasks']) for x in queries))
        for key, field in (('merge_query_wall_ms_sum','merge_query_wall_ms'),
                           ('select_query_wall_ms_sum','select_query_wall_ms'),
                           ('taskgroup_query_wall_ms_sum','taskgroup_query_wall_ms')):
            close(r[key], sum(float(x[field]) for x in queries))
        assert 'statistics=PASS' in (directory / 'diagnostics.log').read_text()
        audit_rows.append(dict(run_id=r['run_id'], repeats=10, batch_samples=len(batches),
                               candidates=total, correctness='PASS', reconciliation='PASS'))
        repeat_count += len(repeats); samples_count += len(batches)
    groups = {}
    for name in manifest['groups']:
        group = rows(source / (name + '.csv'))
        for r in group:
            for k, v in by_id[r['run_id']].items(): assert v == r[k]
            if 'speedup' in r:
                base = by_id[r['serial_baseline_run']]
                assert base['strategy'] == 'serial' and base['batch'] == r['batch']
                close(r['speedup'], float(base['median_ms']) / float(r['median_ms']))
            if 'efficiency' in r: close(r['efficiency'], float(r['speedup']) / int(r['threads']))
            if 'simd_speedup' in r:
                close(r['simd_speedup'], float(by_id[r['off_baseline_run']]['median_ms']) / float(r['median_ms']))
        groups[name] = len(group)
    assert groups == {'A_scaling':24,'B_order':6,'C_grain':4,'D_nprobe':3,'E_simd':8,'std_compare':2,'baseline':2}, groups
    local_root = Path(__file__).resolve().parents[1]
    for name, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((local_root / name).read_bytes()).hexdigest() == digest, name
    data_matches = 0
    for name, entry in manifest['dataset'].items():
        path = local_root / 'dataset' / name
        if path.exists():
            assert digest_file(path) == entry['sha256'], name
            data_matches += 1
    fallback = {}
    for strategy in ('serial','omp2','std'):
        target = source / 'perf' / strategy / 'time_fallback'
        assert json.loads((target / 'status.json').read_text())['status'] == 'whole_process_only'
        rep = rows(target / 'program.csv')
        assert len(rep) == 10 and all(x['correctness'] == 'PASS' for x in rep)
        time_fields = {}
        for line in (target / 'time_verbose.txt').read_text().splitlines():
            for field in ('User time (seconds)', 'System time (seconds)', 'Maximum resident set size (kbytes)',
                          'Voluntary context switches', 'Involuntary context switches', 'Exit status'):
                if line.strip().startswith(field + ':'):
                    time_fields[field] = float(line.rsplit(':',1)[1].strip())
        assert time_fields['Exit status'] == 0
        fallback[strategy] = time_fields
    output.mkdir(parents=True, exist_ok=True)
    result = dict(status='PASS', source_directory=str(source.resolve()), source_commit=(source/'source_commit.log').read_text().splitlines()[-1],
                  configurations=len(summary), formal_repeats=repeat_count, batch_samples=samples_count,
                  diagnostic_runs=len(summary), checked_cpu_endpoints=cpu_samples,
                  groups=groups, locally_matched_dataset_hashes=data_matches,
                  source_hashes_matched=len(manifest['source_sha256']), time_fallback=fallback,
                  limitations=['CPU endpoint observations are not full migration traces.',
                               'Host physical CPU allocation remains unknown in the VM.',
                               'perf kernel tool missing; GNU time covers whole processes.',
                               'grain=4096 has high variance; causal attribution needs a rerun.'])
    (output / 'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    with (output / 'input_files.sha256').open('w') as stream:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                stream.write(f'{digest_file(path)}  {path.relative_to(source)}\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.out)
