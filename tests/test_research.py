import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from sc_rd.research import Costs, evaluate, markdown, read_dataset, run_batch


@pytest.fixture
def case(tmp_path):
    source = Path(__file__).resolve().parents[1]
    config = json.loads((source / 'examples/batch.json').read_text())
    config['dataset'] = 'bars.csv'
    (tmp_path / 'bars.csv').write_bytes((source / 'data/research_ohlc.csv').read_bytes())
    return config, tmp_path


def test_full_batch_costs_and_periods(case):
    config, base = case
    result = evaluate(config, base)
    assert result['mode'] == 'paper-research-only'
    assert len(result['experiments']) == 3
    victor = result['experiments'][0]
    assert victor['trades'][0]['round_trip_cost'] == pytest.approx(.452)
    assert victor['trades'][0]['net_r'] == pytest.approx(2 - .452 / 20)
    for period in victor['periods'].values():
        assert period['closed'] == 2
        assert period['net_metrics']['average_r'] < .5
        assert 'threshold' in period['warnings'][0]
    assert 'No automatic promotion' in markdown(result)


@pytest.mark.parametrize('field', ['fee_per_side', 'fee_bps', 'spread_bps', 'slippage_bps'])
@pytest.mark.parametrize('value', [-1, math.inf, math.nan, True, '1'])
def test_invalid_costs(field, value):
    values = dict(fee_per_side=0, fee_bps=0, spread_bps=0, slippage_bps=0)
    values[field] = value
    with pytest.raises(ValueError):
        Costs(**values)


def test_hashes_and_snapshot(case, monkeypatch):
    config, base = case
    before = copy.deepcopy(config)
    a = evaluate(config, base)
    assert config == before
    assert evaluate(config, base) == a
    (base / 'copy.csv').write_bytes((base / 'bars.csv').read_bytes())
    config['dataset'] = 'copy.csv'
    assert evaluate(config, base)['run_id'] == a['run_id']
    config['costs']['fee_bps'] += 1
    assert evaluate(config, base)['run_id'] != a['run_id']
    config['costs']['fee_bps'] -= 1
    with (base / 'copy.csv').open('a') as f:
        f.write('\n')
    assert evaluate(config, base)['dataset_sha256'] != a['dataset_sha256']
    monkeypatch.setattr('sc_rd.research.engine_fingerprint', lambda: 'different-engine')
    assert evaluate(before, base)['run_id'] != a['run_id']


def test_no_holdout_leakage_and_unresolved_bias(case):
    config, base = case
    config['experiments'] = config['experiments'][:1]
    trades = config['experiments'][0]['trades']
    config['experiments'][0]['trades'] = [trades[0], trades[2]]
    for trade in config['experiments'][0]['trades']:
        trade['plan']['stop'] = 90
        trade['plan']['target'] = 120
    text = (base / 'bars.csv').read_text().replace('2026-02-01T09:00:00Z,100,111,96,108', '2026-02-01T09:00:00Z,100,125,96,120')
    (base / 'bars.csv').write_text(text)
    result = evaluate(config, base)['experiments'][0]
    assert result['trades'][0]['status'] == 'open'
    assert result['trades'][0]['candles_seen'] == 2
    assert result['trades'][0]['net_r'] is None
    assert result['trades'][1]['status'] == 'target'
    assert result['periods']['in_sample']['open'] == 1
    assert any('bias' in w for w in result['periods']['in_sample']['warnings'])


@pytest.mark.parametrize('change', ['reverse', 'duplicate', 'naive', 'bad_ohlc', 'extra_column'])
def test_bad_datasets(case, change):
    _, base = case
    p = base / 'bars.csv'
    rows = p.read_text().splitlines()
    if change == 'reverse':
        rows[1:] = reversed(rows[1:])
    elif change == 'duplicate':
        rows[2] = rows[1]
    elif change == 'naive':
        rows[1] = rows[1].replace('Z', '')
    elif change == 'bad_ohlc':
        rows[1] = rows[1].replace(',100,111', ',nan,111')
    else:
        rows[1] += ',surprise'
    p.write_text('\n'.join(rows))
    with pytest.raises(ValueError):
        read_dataset(p)


@pytest.mark.parametrize('cutoff', ['2025-01-01T00:00:00Z', '2027-01-01T00:00:00Z'])
def test_empty_partition_rejected(case, cutoff):
    config, base = case
    config['split_at'] = cutoff
    with pytest.raises(ValueError, match='both periods'):
        evaluate(config, base)


@pytest.mark.parametrize('change', ['symbol', 'entry', 'overlap', 'unknown_cost', 'unknown_desk', 'minimum', 'policy'])
def test_bad_configuration(case, change):
    config, base = case
    trade = config['experiments'][0]['trades'][0]
    if change == 'symbol':
        trade['plan']['symbol'] = 'OTHER'
    elif change == 'entry':
        trade['plan']['entry'] = 101
    elif change == 'overlap':
        config['experiments'][0]['trades'].insert(1, copy.deepcopy(trade))
    elif change == 'unknown_cost':
        config['costs']['fees_typo'] = 1
    elif change == 'unknown_desk':
        config['experiments'][0]['desk'] = 'live'
    elif change == 'minimum':
        config['minimum_trades'] = True
    else:
        config['ambiguous_policy'] = 'ignore'
    with pytest.raises(ValueError):
        evaluate(config, base)


def test_ambiguous_excluded_and_zero_costs(case):
    config, base = case
    config['ambiguous_policy'] = 'skip'
    config['costs'] = {k: 0 for k in config['costs']}
    result = evaluate(config, base)
    alpha = result['experiments'][1]
    assert alpha['periods']['in_sample']['ambiguous'] == 1
    assert alpha['trades'][0]['net_r'] is None
    victor = result['experiments'][0]['trades'][0]
    assert victor['net_r'] == victor['gross_r'] == 2


def test_short_costs(case):
    config, base = case
    config['experiments'] = config['experiments'][:1]
    for trade in config['experiments'][0]['trades']:
        trade['plan'].update(direction='short', stop=105, target=90)
    result = evaluate(config, base)['experiments'][0]['trades'][0]
    assert result['gross_r'] == -1
    assert result['net_r'] < -1


def test_artifacts_and_cli(case):
    config, base = case
    path = base / 'batch.json'
    path.write_text(json.dumps(config))
    destination = run_batch(path, base / 'reports')
    original = (destination / 'results.json').read_bytes()
    result = json.loads(original)
    assert result['run_id'] == destination.name
    assert 'Findings' in (destination / 'report.md').read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):
        run_batch(path, base / 'reports')
    assert (destination / 'results.json').read_bytes() == original
    cli = subprocess.run([sys.executable, '-m', 'sc_rd', 'batch', str(path), '--output', str(base / 'cli')], capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert result['run_id'] in cli.stdout
    assert (base / 'cli' / result['run_id'] / 'results.json').read_bytes() == original


def test_holdout_changes_cannot_change_in_sample(case):
    config, base = case
    before = evaluate(config, base)
    p = base / 'bars.csv'
    p.write_text(p.read_text().replace('2026-02-01T09:00:00Z,100,111,96,108', '2026-02-01T09:00:00Z,100,102,92,94'))
    after = evaluate(config, base)
    assert before['run_id'] != after['run_id']
    for a, b in zip(before['experiments'], after['experiments']):
        assert a['periods']['in_sample'] == b['periods']['in_sample']


def test_equivalent_timezone_entries(case):
    config, base = case
    config['experiments'][0]['trades'][0]['entry_at'] = '2026-01-01T10:00:00+01:00'
    assert evaluate(config, base)['experiments'][0]['trades'][0]['gross_r'] == 2


def test_strict_json_handles_all_winners(case):
    config, base = case
    config['experiments'] = config['experiments'][:1]
    config['experiments'][0]['trades'] = config['experiments'][0]['trades'][::2]
    result = evaluate(config, base)
    assert result['experiments'][0]['periods']['in_sample']['net_metrics']['profit_factor'] == 'infinite'
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_invalid_cli_creates_no_report(case):
    config, base = case
    config['schema_version'] = 2
    path = base / 'invalid.json'
    path.write_text(json.dumps(config))
    output = base / 'invalid-output'
    cli = subprocess.run([sys.executable, '-m', 'sc_rd', 'batch', str(path), '--output', str(output)], capture_output=True, text=True)
    assert cli.returncode == 2
    assert 'unsupported schema_version' in cli.stderr
    assert not output.exists()
