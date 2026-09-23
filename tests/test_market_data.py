import copy
import json
from pathlib import Path
from unittest.mock import patch,MagicMock
import pytest
from sc_rd.market_data import acquire,normalize,verify_cache,resolve_mapping,run_verified_lab,check_request
from sc_rd.providers.twelve_data import fetch_series,ProviderError
from sc_rd.research import digest

NOW='2026-09-23T20:00:00+00:00'
@pytest.fixture
def request_data():
    return dict(provider_symbol='AAPL',exchange='NASDAQ',mic_code='XNAS',currency='USD',instrument_type='Common Stock',timeframe='15min',start='2026-09-23T13:30:00+00:00',end='2026-09-23T13:45:00+00:00',adjustment_policy='none',max_age_seconds=86400)

@pytest.fixture
def payload():
    return {'status':'ok','meta':dict(symbol='AAPL',exchange='NASDAQ',mic_code='XNAS',currency='USD',type='Common Stock',interval='15min'),
            'values':[dict(datetime=t,open='100',high='102',low='99',close='101') for t in ['2026-09-23 13:30:00','2026-09-23 13:45:00']]}

def test_manifest_hash_and_cache(tmp_path,request_data,payload):
    fetcher=MagicMock(return_value=payload)
    directory=acquire(request_data,tmp_path,now=NOW,fetcher=fetcher)
    assert acquire(request_data,tmp_path,now=NOW,fetcher=fetcher)==directory
    assert fetcher.call_count==1
    m=verify_cache(directory,now=NOW)
    assert m['data_classification']=='REAL' and m['quality_status']=='VERIFIED' and m['evidence_eligible']
    assert m['dataset_sha256']==digest((directory/'candles.csv').read_bytes())
    assert m['t212_ticker'] is None
    assert normalize(payload,request_data,NOW)[0]==(directory/'candles.csv').read_bytes()
    changed=dict(request_data,max_age_seconds=90000)
    assert acquire(changed,tmp_path,now=NOW,fetcher=fetcher)!=directory

@pytest.mark.parametrize('mutation',['empty','duplicate','reverse','geometry','zero','negative','nan','inf','identity','gap','malformed','status'])
def test_rejections(request_data,payload,mutation):
    if mutation=='empty':payload['values']=[]
    elif mutation=='duplicate':payload['values'][1]=payload['values'][0]
    elif mutation=='reverse':payload['values'].reverse()
    elif mutation=='identity':payload['meta']['currency']='GBP'
    elif mutation=='gap':payload['values'][1]['datetime']='2026-09-23 14:00:00'
    elif mutation=='malformed':payload['values'][0].pop('open')
    elif mutation=='status':payload['status']='error'
    else:payload['values'][0]['high']={'geometry':'98','zero':'0','negative':'-1','nan':'NaN','inf':'inf'}[mutation]
    with pytest.raises(ValueError):normalize(payload,request_data,NOW)

@pytest.mark.parametrize('field,value',[('data_classification','SYNTHETIC'),('quality_status','REJECTED'),('evidence_eligible',False),('dataset_sha256','0'*64),('row_count',999)])
def test_tamper_and_synthetic_blocked(tmp_path,request_data,payload,field,value):
    directory=acquire(request_data,tmp_path,now=NOW,fetcher=lambda _:payload)
    p=directory/'manifest.json';m=json.loads(p.read_text());m[field]=value;p.write_text(json.dumps(m))
    with pytest.raises(ValueError):verify_cache(directory,now=NOW)

def test_missing_credentials(request_data):
    with patch.dict('os.environ',{},clear=True),patch('http.client.HTTPSConnection') as client:
        with pytest.raises(ProviderError,match='MISSING_CREDENTIAL'):fetch_series(request_data)
        client.assert_not_called()

@pytest.mark.parametrize('status,body',[(401,b''),(403,b''),(429,b''),(302,b''),(200,b'not json'),(200,b'{"status":"error","code":401,"message":"PRIVATE"}')])
def test_provider_errors_sanitized(request_data,status,body):
    c=MagicMock();c.getresponse.return_value.status=status;c.getresponse.return_value.read.return_value=body
    with patch.dict('os.environ',{'TWELVE_DATA_API_KEY':'SECRET_SENTINEL'}),patch('http.client.HTTPSConnection',return_value=c):
        with pytest.raises(ProviderError) as exc:fetch_series(request_data)
        assert 'SECRET_SENTINEL' not in str(exc.value) and 'PRIVATE' not in str(exc.value)
        assert c.request.call_count==1

def test_response_has_no_secret_in_manifest(request_data,payload):
    payload['secret']='SECRET_SENTINEL';payload['meta']['Authorization']='SECRET_SENTINEL'
    raw,m=normalize(payload,request_data,NOW)
    assert 'SECRET_SENTINEL' not in json.dumps(m)+raw.decode()

def test_stale_and_incomplete(request_data,payload):
    for now in ['2026-09-23T13:46:00+00:00','2026-09-25T20:00:00+00:00']:
        with pytest.raises(ValueError):normalize(payload,request_data,now)

def test_ambiguous_mapping():
    identity=dict(isin='US0378331005',currency='USD',instrument_type='Common Stock',provider_symbol='AAPL',exchange='NASDAQ')
    item=dict(isin='US0378331005',currencyCode='USD',type='STOCK',ticker='AAPL_US_EQ')
    with pytest.raises(ValueError):resolve_mapping(identity,[item,item])
    with pytest.raises(ValueError):resolve_mapping(dict(identity,isin=None),[item])

def test_real_lab_adapter(tmp_path,request_data,payload):
    from datetime import datetime,timedelta
    request_data['end']='2026-09-23T19:45:00+00:00'
    start=datetime.fromisoformat(request_data['start'])
    payload['values']=[dict(datetime=(start+timedelta(minutes=15*i)).isoformat(),open='100',high='102',low='99',close='101') for i in range(26)]
    directory=acquire(request_data,tmp_path/'cache',now=NOW,fetcher=lambda _:payload)
    config=Path(__file__).resolve().parents[1]/'examples/cloud_lab.json'
    result=run_verified_lab(directory,config,tmp_path/'reports',now=NOW)
    r=json.loads((result/'results.json').read_text())
    assert r['data_classification']=='REAL' and r['evidence_status']=='PROVISIONAL'
    assert r['final_holdout'] is None
    assert r['provenance']['dataset_sha256']==r['dataset_sha256']
