"""§12 增量優化架構 + 6 個 5T 合規模式 回歸測試。

Free-local: no network, no cloud keys. Every pattern must route through
gate5t (5T single source of truth) and support incremental output
(delta / pagination / compression / cache).
"""

import gzip
import json

from src import incremental as inc
from src.gate5t import verify_locked


# ---------------------------------------------------------------------------
# Incremental primitives
# ---------------------------------------------------------------------------

def test_stream_buffer_delta():
    buf = inc.StreamBuffer()
    buf.append({"v": 1})
    buf.append({"v": 2})
    s1 = buf.append({"v": 3})
    delta = buf.get_delta(since=s1 - 1)  # only the last one
    assert len(delta) == 1
    assert delta[0]["v"] == 3
    assert buf.size == 3


def test_worker_pool_process_delta_filters_none():
    pool = inc.WorkerPool(workers=2)
    out = list(pool.process_delta([1, 2, 3, 4], lambda x: x * 2 if x % 2 == 0 else None))
    assert sorted(out) == [4, 8]  # only evens transformed


def test_delta_tracker_only_reports_changes():
    t = inc.DeltaTracker()
    assert t.get_changes({"a": 1}) == {"a": 1}      # first time: changed
    t.apply({"a": 1})
    assert t.get_changes({"a": 1}) == {}            # unchanged: empty
    assert t.get_changes({"a": 2}) == {"a": 2}      # changed again


def test_compression_roundtrip():
    data = {"rows": list(range(50))}
    blob = inc.CompressionEngine.compress(data)
    assert isinstance(blob, bytes)
    assert len(blob) < len(json.dumps(data).encode())  # smaller
    assert inc.CompressionEngine.decompress(blob) == data


def test_lru_cache_ttl_and_eviction():
    c = inc.LRUCache(maxsize=2, ttl=0)  # ttl=0 -> immediate expiry
    c.set("k", "v")
    assert c.get("k") is None  # expired
    c2 = inc.LRUCache(maxsize=2, ttl=999)
    c2.set("a", 1)
    c2.set("b", 2)
    c2.set("c", 3)  # evicts oldest (a)
    assert "a" not in c2


def test_paginate_envelope():
    items = list(range(25))
    p1 = inc.paginate(items, page=1, size=10)
    assert p1["total"] == 25 and p1["pages"] == 3 and p1["items"] == list(range(10))
    p3 = inc.paginate(items, page=3, size=10)
    assert p3["items"] == [20, 21, 22, 23, 24]


def test_5t_lock_helper_frozen():
    art = inc._make_artifact("u1", "origin-x", "test")
    locked = inc.lock_5t(art, kind="test")
    assert verify_locked(locked)
    assert locked.hash_lock


# ---------------------------------------------------------------------------
# Pattern 1: EventBus
# ---------------------------------------------------------------------------

def test_eventbus_publish_and_delta():
    bus = inc.EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    seq1 = bus.publish({"source": "svc-a", "msg": "hi"})
    seq2 = bus.publish({"source": "svc-a", "msg": "bye"})
    assert seq2 > seq1
    assert len(seen) == 2
    # incremental: only events after seq1
    delta = bus.get_events(since=seq1)
    assert len(delta) == 1
    assert delta[0]["payload"]["msg"] == "bye"


def test_eventbus_locked_artifact_frozen():
    bus = inc.EventBus()
    bus.publish({"source": "svc-b", "x": 1})
    # the published event is hashed+stored; re-verify via log entry hash
    evts = bus.get_events()
    assert "hash_lock" in evts[0]


# ---------------------------------------------------------------------------
# Pattern 2: ServiceOrchestrator
# ---------------------------------------------------------------------------

def test_orchestrator_execute_and_page():
    o = inc.ServiceOrchestrator()
    res = o.execute_workflow({
        "source": "orc", "services": ["a", "b", "c", "d", "e"],
        "page": 1, "ui_feedback": "done",
    })
    assert res["execution_id"]
    assert res["hash_lock"]
    # paginated envelope: 5 services, page size 10 -> all on page 1
    assert res["page"]["items"] == [{"service": s, "status": "ok"} for s in ["a", "b", "c", "d", "e"]]
    # get_page from cache
    cached = o.get_page(res["execution_id"], page=1)
    assert cached is not None and cached["total"] == 5


def test_orchestrator_requires_services():
    o = inc.ServiceOrchestrator()
    try:
        o.execute_workflow({"source": "orc"})
        assert False, "should have raised"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Pattern 3: ETLPipeline
# ---------------------------------------------------------------------------

def test_etl_process_delta_and_compress():
    p = inc.ETLPipeline()
    r1 = p.process({"id": "t1", "source": "db", "rows": [1, 2, 3]})
    assert r1["changed_rows"] == 3
    assert r1["compressed_bytes"] > 0
    # second run with same rows -> no change
    r2 = p.process({"id": "t1", "source": "db", "rows": [1, 2, 3]})
    assert r2["changed_rows"] == 0
    # new row -> 1 change
    r3 = p.process({"id": "t1", "source": "db", "rows": [1, 2, 3, 4]})
    assert r3["changed_rows"] == 1


# ---------------------------------------------------------------------------
# Pattern 4: APIGateway
# ---------------------------------------------------------------------------

def test_gateway_unauth_without_sig():
    g = inc.APIGateway()
    resp = g.handle_request({"client_id": "c1", "signature": "", "timestamp": "", "body": {}}, secret="s3cr3t")
    assert resp["ok"] is False and resp["error"] == "unauthorized"


def test_gateway_ok_paginated():
    g = inc.APIGateway()
    resp = g.handle_request({
        "client_id": "c1", "cache_key": "k1", "page": 1,
        "items": list(range(15)),
    })
    assert resp["ok"] is True
    assert resp["page"]["total"] == 15
    assert len(resp["page"]["items"]) == 10  # page size default
    # second call hits cache
    resp2 = g.handle_request({"client_id": "c1", "cache_key": "k1", "page": 2, "items": list(range(15))})
    assert resp2["cached"] is True


def test_gateway_access_log_delta():
    g = inc.APIGateway()
    g.handle_request({"client_id": "c2", "cache_key": "x", "items": []})
    log1 = g.get_access_log()
    assert len(log1) == 1
    g.handle_request({"client_id": "c2", "cache_key": "y", "items": []})
    g.handle_request({"client_id": "c2", "cache_key": "y", "items": []})
    delta = g.get_access_log(since=len(log1))
    assert len(delta) == 2


# ---------------------------------------------------------------------------
# Pattern 5: CacheManager
# ---------------------------------------------------------------------------

def test_cache_hit_rate_tracked():
    cm = inc.CacheManager()
    assert cm.get("missing") is None  # miss
    cm.set("k", {"a": 1})
    assert cm.get("k") == {"a": 1}    # hit
    stats = cm.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert abs(stats["hit_rate"] - 0.5) < 1e-9


def test_cache_batch_delta_merge():
    cm = inc.CacheManager()
    cm.batch_update_delta([{"key": "u", "delta": {"name": "x"}, "version": 1}])
    assert cm.get("u") == {"name": "x"}
    cm.batch_update_delta([{"key": "u", "delta": {"age": 5}, "version": 2}])
    assert cm.get("u") == {"name": "x", "age": 5}


def test_cache_stale_detection():
    cm = inc.CacheManager()
    cm.set("v", 1, version="1.0")
    assert cm.is_stale("v", "1.0") is False
    assert cm.is_stale("v", "2.0") is True
    assert cm.fetch_delta("v", "1.0") is None      # not stale -> None
    assert cm.fetch_delta("v", "2.0") == 1          # stale -> returns value


# ---------------------------------------------------------------------------
# Pattern 6: ErrorHandler
# ---------------------------------------------------------------------------

def test_error_handler_records_and_retries():
    eh = inc.ErrorHandler(max_retries=3)
    eid = eh.handle(ValueError("boom"), {"retry_count": 0})
    assert eid
    pending = eh.pending_retries()
    assert len(pending) == 1
    assert pending[0]["delay"] == 1000  # 2^0 * 1000
    logs = eh.get_error_logs()
    assert logs["total"] == 1 and "boom" in logs["items"][0]["error"]


def test_error_handler_no_retry_past_threshold():
    eh = inc.ErrorHandler(max_retries=3)
    eh.handle(RuntimeError("x"), {"retry_count": 3})
    assert eh.pending_retries() == []  # no more retries


def test_error_handler_log_pagination():
    eh = inc.ErrorHandler()
    for i in range(25):
        eh.handle(ValueError(str(i)), {"retry_count": 0})
    p1 = eh.get_error_logs(page=1)
    assert p1["total"] == 25 and len(p1["items"]) == 10
    p3 = eh.get_error_logs(page=3)
    assert p3["items"][-1]["error"] == "24"
