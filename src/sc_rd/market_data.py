"""Verified intraday US research datasets; fail closed, with no synthetic fallback."""
from __future__ import annotations
import csv
import io
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .research import canonical, digest, fields, instant, read_dataset
from .providers.twelve_data import fetch_series

INTERVALS = {'1min': 60, '5min': 300, '15min': 900, '30min': 1800}


def check_request(request):
    fields(request, {'provider_symbol','exchange','mic_code','currency','instrument_type',
                     'timeframe','start','end','adjustment_policy','max_age_seconds'}, 'market request')
    if request['exchange'] not in {'NASDAQ','NYSE','NYSE ARCA'} or request['currency'] != 'USD':
        raise ValueError('only USD US-listed instruments are supported')
    if not isinstance(request['mic_code'], str) or len(request['mic_code']) != 4:
        raise ValueError('explicit MIC required')
    if request['instrument_type'] not in {'Common Stock','ETF'}:
        raise ValueError('unsupported instrument type')
    symbol = request['provider_symbol']
    if not isinstance(symbol,str) or not (1 <= len(symbol) <= 16) or not all(c.isascii() and (c.isupper() or c.isdigit() or c in '.-') for c in symbol):
        raise ValueError('invalid explicit provider symbol')
    if request['timeframe'] not in INTERVALS or request['adjustment_policy'] != 'none':
        raise ValueError('initial gateway supports intraday unadjusted candles only')
    if type(request['max_age_seconds']) is not int or not 1 <= request['max_age_seconds'] <= 366*86400:
        raise ValueError('explicit bounded freshness policy required')
    start,end = instant(request['start']),instant(request['end'])
    if request['start'] != start.isoformat() or request['end'] != end.isoformat():
        raise ValueError('request timestamps must be canonical UTC ISO strings')
    step = INTERVALS[request['timeframe']]
    if end < start or (end-start).total_seconds()%step or (end-start).total_seconds()/step+1 > 5000:
        raise ValueError('invalid bounded request coverage')
    local_start,local_end = start.astimezone(ZoneInfo('America/New_York')),end.astimezone(ZoneInfo('America/New_York'))
    # Deliberately narrow: a contiguous interval within one regular session.
    # No guessed holidays or overnight gap repair. A closure fails coverage.
    if local_start.date()!=local_end.date() or local_start.weekday()>4 or (local_start.hour,local_start.minute)<(9,30) or (local_end+timedelta(seconds=step)).hour>16 or local_end+timedelta(seconds=step)>local_end.replace(hour=16,minute=0,second=0,microsecond=0):
        raise ValueError('request must fit a single US regular session')
    if start.second or start.microsecond or (local_start.hour*60+local_start.minute-570)*60%step:
        raise ValueError('request must align to session candle boundaries')
    return start,end,step


def resolve_mapping(provider_identity, instruments):
    """Optional exact ISIN join. Never infer a broker ticker from a symbol."""
    isin = provider_identity.get('isin')
    if not isinstance(isin,str) or len(isin)!=12:
        raise ValueError('independently resolved provider ISIN required for T212 mapping')
    candidates = [i for i in instruments if i.get('isin') == isin and i.get('currencyCode') == provider_identity['currency']
                  and i.get('type') == {'Common Stock':'STOCK','ETF':'ETF'}.get(provider_identity['instrument_type'])]
    if len(candidates)!=1 or not candidates[0].get('ticker'):
        raise ValueError('ambiguous or missing T212 identity mapping')
    if candidates[0].get('exchange') != provider_identity.get('exchange'):
        raise ValueError('broker listing venue is not independently resolved')
    return {'t212_ticker':candidates[0]['ticker'],'isin':isin,'provider_symbol':provider_identity['provider_symbol'],
            'exchange':provider_identity['exchange'],'currency':provider_identity['currency'],
            'instrument_type':provider_identity['instrument_type'],'mapping_basis':'exact ISIN/currency/type/exchange'}


def normalize(payload, request, acquired_at):
    start,end,step = check_request(request)
    now = instant(acquired_at)
    if now < end+timedelta(seconds=step) or (now-end).total_seconds()>request['max_age_seconds']:
        raise ValueError('incomplete or stale dataset for the requested experiment')
    if not isinstance(payload,dict) or payload.get('status')!='ok' or not isinstance(payload.get('meta'),dict):
        raise ValueError('malformed provider response')
    meta=payload['meta']
    expected={'symbol':request['provider_symbol'],'exchange':request['exchange'],'mic_code':request['mic_code'],
              'currency':request['currency'],'type':request['instrument_type'],'interval':request['timeframe']}
    if any(meta.get(k)!=v for k,v in expected.items()):
        raise ValueError('provider identity or timeframe mismatch')
    values=payload.get('values')
    if not isinstance(values,list) or not values:
        raise ValueError('empty or malformed dataset')
    rows=[];times=[]
    for row in values:
        if not isinstance(row,dict):raise ValueError('malformed candle')
        try:
            time=datetime.fromisoformat(row['datetime'])
            # Endpoint was explicitly requested in UTC; naive provider labels refer to UTC.
            time=time.replace(tzinfo=timezone.utc) if time.tzinfo is None else time.astimezone(timezone.utc)
            prices=[float(row[k]) for k in ('open','high','low','close')]
        except (ValueError,TypeError,KeyError):raise ValueError('malformed candle') from None
        if any(not math.isfinite(p) or p<=0 for p in prices):raise ValueError('nonpositive or nonfinite price')
        o,h,l,c=prices
        if h<max(o,l,c) or l>min(o,h,c):raise ValueError('invalid OHLC geometry')
        times.append(time);rows.append([time.isoformat(),*(format(p,'.17g') for p in prices)])
    if len(set(times))!=len(times):raise ValueError('duplicate timestamps')
    if any(a>=b for a,b in zip(times,times[1:])):raise ValueError('non-monotonic timestamps')
    expected_count=int((end-start).total_seconds()/step)+1
    if times[0]!=start or times[-1]!=end or len(times)!=expected_count or any((b-a).total_seconds()!=step for a,b in zip(times,times[1:])):
        raise ValueError('missing bars or requested coverage not satisfied')
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\n')
    writer.writerow(['timestamp','open','high','low','close']);writer.writerows(rows)
    raw=stream.getvalue().encode()
    manifest={'schema_version':1,'data_classification':'REAL','evidence_eligible':True,
              'quality_status':'VERIFIED','provider':'Twelve Data','provider_symbol':request['provider_symbol'],
              't212_ticker':None,'isin':None,'mapping_status':'PROVIDER_IDENTITY_VERIFIED_BROKER_UNLINKED',
              'instrument_type':request['instrument_type'],'exchange':request['exchange'],'mic_code':request['mic_code'],
              'currency':'USD','timeframe':request['timeframe'],'timezone':'UTC','first_candle':times[0].isoformat(),
              'last_candle':times[-1].isoformat(),'acquired_at':now.isoformat(),'adjustment_policy':request['adjustment_policy'],
              'row_count':len(rows),'missing_candle_count':0,'duplicate_count':0,'dataset_sha256':digest(raw),
              'request':request,'normalization_version':1,
              'warnings':['UTC explicitly requested; labels normalized to aware UTC; OHLC serialized as finite float round-trip values.',
                          'Provider identity is checked, not a claim of T212 tradability or a validated trading edge.',
                          'Single regular-session coverage only; no holiday inference, interpolation, or missing-bar repair.']}
    return raw,manifest


def verify_cache(directory, *, now=None):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('data_classification')!='REAL' or manifest.get('evidence_eligible') is not True or manifest.get('quality_status')!='VERIFIED' or manifest.get('provider')!='Twelve Data':
        raise ValueError('only VERIFIED REAL datasets may enter research')
    candles,times,sha=read_dataset(directory/'candles.csv')
    if sha!=manifest['dataset_sha256']:raise ValueError('cached fingerprint mismatch')
    request=manifest['request'];start,end,step=check_request(request)
    now=instant(now) if now else datetime.now(timezone.utc)
    if now<instant(manifest['acquired_at']) or now<end+timedelta(seconds=step) or (now-end).total_seconds()>request['max_age_seconds']:
        raise ValueError('cached data stale or future-dated')
    payload={'status':'ok','meta':{'symbol':request['provider_symbol'],'exchange':request['exchange'],'mic_code':request['mic_code'],
        'currency':request['currency'],'type':request['instrument_type'],'interval':request['timeframe']},
        'values':[{'datetime':c.timestamp,'open':c.open,'high':c.high,'low':c.low,'close':c.close} for c in candles]}
    _,expected=normalize(payload,request,manifest['acquired_at'])
    if canonical(expected)!=canonical(manifest):raise ValueError('cache manifest mismatch')
    return manifest


def acquire(request, cache, *, now=None, fetcher=fetch_series):
    request=json.loads(canonical(request));check_request(request)
    now=now or datetime.now(timezone.utc).isoformat()
    key=digest(canonical({'provider':'Twelve Data','version':1,'request':request}).encode())
    directory=Path(cache)/key
    if directory.exists():
        manifest=verify_cache(directory,now=now)
        if manifest['request']!=request:raise ValueError('cache request mismatch')
        return directory
    # Fetch and gate before creating an accepted cache entry. No synthetic fallback.
    try:
        raw,manifest=normalize(fetcher(request),request,now)
    except Exception:
        rejected=Path(cache)/'rejected'/key
        rejected.mkdir(parents=True,exist_ok=True)
        record={'schema_version':1,'data_classification':'REAL','evidence_eligible':False,
                'quality_status':'REJECTED','provider':'Twelve Data','request':request,
                'dataset_sha256':None,'acquired_at':now,'reason':'PROVIDER_OR_QUALITY_GATE_FAILED'}
        # A separate immutable rejection record; never an accepted cache entry.
        path=rejected/(digest(canonical(record).encode())+'.json')
        if not path.exists():path.write_text(canonical(record)+'\n',encoding='utf-8')
        raise
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'candles.csv').write_bytes(raw)
    (directory/'manifest.json').write_text(canonical(manifest)+'\n',encoding='utf-8')
    return directory


def run_verified_lab(cache, config_path, output, *, now=None):
    """Reuse the existing lab; no provider logic or holdout-reveal option in strategies."""
    from .lab import evaluate_lab,lab_markdown
    manifest=verify_cache(cache,now=now)
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    config['dataset']=str((Path(cache)/'candles.csv').resolve())
    config['symbol']=manifest['provider_symbol']
    result=evaluate_lab(config,Path('.'),include_holdout=False)
    if result['dataset_sha256']!=manifest['dataset_sha256']:raise ValueError('dataset changed during evaluation')
    result.update(data_classification='REAL',evidence_status='PROVISIONAL',evidence_eligible=True,provenance=manifest)
    result['run_id']=digest(canonical({'engine_run':result['run_id'],'provenance':manifest}).encode())
    directory=Path(output)/result['run_id'];directory.mkdir(parents=True,exist_ok=False)
    (directory/'results.json').write_text(canonical(result)+'\n',encoding='utf-8')
    report=lab_markdown(result).replace('TEST_ONLY — software-test output; excluded from trading evidence.', 'REAL / VERIFIED dataset. PROVISIONAL research; no validated edge.')
    (directory/'report.md').write_text(report,encoding='utf-8')
    return directory


def run_verified_portfolio(cache, config_path, output, *, now=None):
    """Minimal single-instrument adapter, preserving all shared-cash replay rules."""
    from .portfolio import run_portfolio, report
    from .research import engine_fingerprint
    manifest=verify_cache(cache,now=now)
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    symbol=manifest['provider_symbol']
    if set(config['datasets'])!={symbol}:
        raise ValueError('verified portfolio requires exactly the resolved provider symbol')
    config['datasets']={symbol:str((Path(cache)/'candles.csv').resolve())}
    identity={'provenance':manifest,'config':{**config,'datasets':[symbol]},'engine':engine_fingerprint()}
    outer=Path(output)/digest(canonical(identity).encode());outer.mkdir(parents=True,exist_ok=False)
    spec=outer/'prepared.json';spec.write_text(canonical(config),encoding='utf-8')
    directory=run_portfolio(spec,outer,period='development')
    result=json.loads((directory/'results.json').read_text(encoding='utf-8'))
    if result['identity']['datasets']!={symbol:manifest['dataset_sha256']}:
        raise ValueError('dataset changed during replay')
    result.update(data_classification='REAL',evidence_status='PROVISIONAL',evidence_eligible=True,provenance=manifest)
    result['identity']['provenance_sha256']=digest(canonical(manifest).encode())
    (directory/'results.json').write_text(canonical(result)+'\n',encoding='utf-8')
    (directory/'report.md').write_text(report(result).replace('TEST_ONLY — software-test output; excluded from trading evidence.',
        'REAL / VERIFIED dataset. PROVISIONAL research; no validated edge.'),encoding='utf-8')
    return directory
