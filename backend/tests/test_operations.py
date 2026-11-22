"""Operational invariants: validation selection, evidence, persistence and replay."""
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config.settings import Settings
from backend.app.services import alerts, alert_delivery, delay_prediction, processed_historical
from backend.app.schemas.intelligence import AlertRead
from backend.app.streaming import consumer, store
from backend.app.streaming.event import Observation
from backend.app.streaming import producer

client = TestClient(app)


def test_public_adsb_conversion_preserves_source_and_units(monkeypatch):
    stamp=int(time.time())*1000
    monkeypatch.setattr(producer,'get_airspace',lambda *args:{'time':stamp,'aircraft':[
        dict(id='abc123',callsign='ABC1',lat=40.,lon=-74.,observed=stamp-2000,ground=False,
             altitude=10000.,speed=194.384,heading=90.,verticalRate=196.85,squawk=None),
        dict(id='~badid',callsign='invalid'),
    ]})
    timestamp,states=producer.adsb_snapshot(39,-75,41,-73)
    assert timestamp==stamp//1000
    assert len(states)==1
    assert states[0].last_contact==timestamp-2
    assert states[0].barometric_altitude_m==3048
    assert states[0].velocity_mps==pytest.approx(100)
    assert states[0].vertical_rate_mps==pytest.approx(1)
    assert Observation(version=1,source='adsb_lol',source_time=timestamp,state=states[0]).source=='adsb_lol'


def test_forecast_rejects_same_airport():
    response=client.post('/api/v1/predictions/delay',json={'reporting_airline':'AA','origin':'JFK','destination':'jfk','flight_date':'2024-02-01'})
    assert response.status_code==422


def event(source="opensky", age=0, rate=40):
    now = int(time.time()) - age
    return Observation.model_validate({"version":1,"source":source,"source_time":now,"state":{
        "icao24":"abc123", "callsign":"TEST123", "origin_country":"US", "time_position":now,
        "last_contact":now,"longitude":-74.,"latitude":40.,"on_ground":False,"velocity_mps":100.,
        "vertical_rate_mps":rate,"barometric_altitude_m":1000.,"geometric_altitude_m":None,
        "true_track_degrees":90.,"squawk":None,"spi":False,"position_source":0,
    }})


def test_best_model_uses_validation_and_falls_back(tmp_path, monkeypatch):
    directory = tmp_path / delay_prediction.MODEL_DIRECTORY
    directory.mkdir(parents=True)
    metrics = {candidate:{"f2":i/10,"pr_auc":.3,"recall":.2,"precision":.3}
               for i,candidate in enumerate(delay_prediction.MODEL_CANDIDATES.values())}
    (directory / "validation_metrics.json").write_text(json.dumps({"candidates":metrics}))
    monkeypatch.setattr(delay_prediction,"get_settings",lambda:SimpleNamespace(data_directory=tmp_path))
    calls=[]
    def load(name):
        calls.append(name)
        if name=="xgboost":
            raise delay_prediction.PredictionUnavailable("missing")
        return object(),{}
    monkeypatch.setattr(delay_prediction,"_load_model",load)
    name,selection=delay_prediction.select_best_model()
    assert name=="decision-tree"
    assert calls==["xgboost","decision-tree"]
    assert selection["compared_models"]==4
    assert selection["unavailable_models"]==["xgboost"]


def test_invalid_metrics_do_not_silently_select_a_model(tmp_path,monkeypatch):
    directory=tmp_path / delay_prediction.MODEL_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "validation_metrics.json").write_text('{"candidates":{}}')
    monkeypatch.setattr(delay_prediction,"get_settings",lambda:SimpleNamespace(data_directory=tmp_path))
    with pytest.raises(delay_prediction.PredictionUnavailable):
        delay_prediction.select_best_model()


def test_historical_alert_reads_source_and_deduplicates(monkeypatch):
    row=SimpleNamespace(arrival_delay_minutes=45,cancelled=0,diverted=0,
        delay_reasons=[{"label":"Weather","minutes":30}], flight_date="2024-02-01",
        reporting_airline="AA",flight_number="123",origin_bts_code="JFK",destination_bts_code="ORD",airline_name="American Airlines")
    monkeypatch.setattr(processed_historical,"search_processed_flights",lambda **kwargs:([row],1))
    payload={"source_file":"bts_ontime_2024_02.parquet","source_row_number":3}
    first=client.post('/api/v1/alerts/historical',json=payload)
    assert first.status_code==200
    alert=first.json()
    assert "Weather: 30 min" in alert["explanation"]
    assert alert["source"]=="historical_bts"
    assert client.post('/api/v1/alerts/historical',json=payload).json()["id"]==alert["id"]
    assert client.get('/api/v1/alerts').json()["pagination"]["total"]==1
    assert client.patch('/api/v1/alerts/'+alert["id"],json={"status":"acknowledged"}).json()["status"]=="acknowledged"
    assert client.patch('/api/v1/alerts/'+alert["id"],json={"status":"resolved"}).json()["status"]=="resolved"
    assert client.patch('/api/v1/alerts/'+alert["id"],json={"status":"acknowledged"}).status_code==409
    assert client.post('/api/v1/alerts/historical',json=payload).json()["status"]=="resolved"
    assert client.post('/api/v1/alerts/historical',json={**payload,"arrival_delay_minutes":100}).status_code==422


def test_historical_alert_rejects_on_time_and_unknown_records(monkeypatch):
    monkeypatch.setattr(processed_historical,"search_processed_flights",lambda **kwargs:([],0))
    payload={"source_file":"unknown","source_row_number":1}
    assert client.post('/api/v1/alerts/historical',json=payload).status_code==404
    monkeypatch.setattr(processed_historical,"search_processed_flights",lambda **kwargs:([SimpleNamespace(arrival_delay_minutes=0,cancelled=0,diverted=0)],1))
    assert client.post('/api/v1/alerts/historical',json=payload).status_code==422


def test_consumer_replay_staleness_and_simulation_are_separate(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"get_settings",lambda:SimpleNamespace(data_directory=tmp_path))
    live=event()
    consumer.ingest(b'abc123',live.model_dump_json().encode(),0,1)
    consumer.ingest(b'abc123',live.model_dump_json().encode(),0,1)
    assert store.latest_states()["status"]=="available"
    assert len(store.latest_states()["aircraft"])==1
    assert store.summary('opensky')["windows"][0]["observations"]==1
    assert alerts.list_alerts(page=1,page_size=10)[1]==1
    sim=event('SIMULATION')
    consumer.ingest(b'abc123',sim.model_dump_json().encode(),0,2)
    assert alerts.list_alerts(page=1,page_size=10)[1]==1
    assert len(store.latest_states()["aircraft"])==1
    consumer.ingest(b'wrong-key',live.model_dump_json().encode(),0,3)
    with sqlite3.connect(store.database()) as db:
        assert db.execute('SELECT count(*) FROM rejected').fetchone()[0]==1
        db.execute("UPDATE observations SET observed=observed-400 WHERE source='opensky'")
    assert store.latest_states()["status"]=="stale"
    assert store.latest_states()["aircraft"]==[]


def test_simulation_and_old_telemetry_never_create_live_alerts():
    assert alerts.create_observation_alert(event('SIMULATION')) is None
    assert alerts.create_observation_alert(event(age=400)) is None
    assert alerts.create_observation_alert(event(rate=None)) is None
    assert alerts.list_alerts(page=1,page_size=10)[1]==0


def test_delivery_persists_failure_and_success_without_losing_ack(tmp_path,monkeypatch):
    settings=Settings(data_directory=tmp_path,smtp_host='smtp.example.test',smtp_from='from@example.test',alert_email_to='to@example.test',_env_file=None)
    monkeypatch.setattr(alerts,'get_settings',lambda:settings)
    monkeypatch.setattr(alert_delivery,'get_settings',lambda:settings)
    alert=alerts.create_observation_alert(event())
    assert alert.delivery_status=='pending'
    alerts.update_alert(alert.id,'acknowledged')
    def fail(message):
        raise OSError('sensitive provider message')
    assert alert_delivery.deliver_pending(send=fail)
    rows,_=alerts.list_alerts(page=1,page_size=10)
    assert rows[0].delivery_status=='failed'
    assert rows[0].delivery_error=='OSError'
    assert rows[0].status=='acknowledged'
    assert alert_delivery.deliver_pending(send=lambda msg:None) is False
    with alerts.alert_database() as db:
        db.execute('UPDATE email_jobs SET retry_at=0')
    messages=[]
    assert alert_delivery.deliver_pending(send=messages.append)
    rows,_=alerts.list_alerts(page=1,page_size=10)
    assert rows[0].delivery_status=='sent'
    assert messages[0]['To']=='to@example.test'
    assert alert_delivery.deliver_pending(send=messages.append) is False
