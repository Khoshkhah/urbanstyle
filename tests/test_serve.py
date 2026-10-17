"""urbanstyle serve (docs/design/dashboard-v2.md): the agent's queries are read-only, and the agent's tool loop runs its tools and
gives their results back (a fake model, no network)."""
import json
import sys
import types
from types import SimpleNamespace as NS

import pytest

from urbanstyle.serve import Agent, read_only


def test_read_only_accepts_one_select_and_refuses_the_rest():
    assert read_only("SELECT 1;") == "SELECT 1"
    assert read_only("with a as (select 1) select * from a")
    assert read_only("SELECT 'drop table' AS note")        # (a word in a string is no statement)
    for bad in ("DROP TABLE work.part", "SELECT 1; DROP TABLE x", "ATTACH 'x.db'", "SELECT * FROM read_csv('/etc/passwd')",
                "COPY work.part TO 'x.csv'", "SELECT * FROM st_read('x.shp')", "INSTALL httpfs"):
        with pytest.raises(ValueError):
            read_only(bad)


def test_agent_runs_its_tools_and_answers(monkeypatch):
    calls = []

    class Area:
        name, epsg = "test", "EPSG:32610"
        schema = lambda self: "work.part (2 rows): part_id VARCHAR, type VARCHAR, width_m DOUBLE"
        run_sql = lambda self, sql: json.dumps({"rows": [{"n": 2}], "more_rows": False})
        features = lambda self, sql: {"features": [{}, {}], "total": 2, "length_m": 0, "area_m2": 30.0, "kinds": [["sidewalk", 2]]}

    replies = [NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="run_sql", input={"sql": "SELECT count(*) n FROM work.part"}),
                                                   NS(type="tool_use", id="t2", name="show_on_map", input={"sql": "SELECT * FROM work.part", "title": "sidewalks"})]),
               NS(stop_reason="end_turn", content=[NS(type="text", text="There are 2 sidewalks (OSM, mapped).")])]

    def create(**kw):
        calls.append({**kw, "messages": list(kw["messages"])})     # (the list grows after the call)
        return replies[len(calls) - 1]
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kw: NS(beta=NS(messages=NS(create=create)))
    for e in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(fake, e, type(e, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")      # (Claude: with no Anthropic key and a Gemini key the agent is Gemini)
    r = Agent(Area()).ask("s1", "How many sidewalks?")
    assert r["answer"] == "There are 2 sidewalks (OSM, mapped)."
    assert r["fresh"]          # (a new conversation; after `forget` the next one is new again)
    assert [q["sql"] for q in r["queries"]] == ["SELECT count(*) n FROM work.part", "SELECT * FROM work.part"]
    assert r["map"]["title"] == "sidewalks" and r["map"]["total"] == 2
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["fallbacks"] == "default"
    # the second call carries both tool results in one user message, after the assistant's turn
    msgs = calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["t1", "t2"]


def test_gemini_goes_on_to_the_next_model(monkeypatch):
    """Gemini: a model overloaded now (503) or with its day used up (429 per day) is left for the next one in the list; the answer
    comes from the first that works (a fake client, no network)."""
    genai = pytest.importorskip("google.genai")
    import urbanstyle.serve as sv
    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == sv.GEMINI_NEXT[0]:
                raise RuntimeError("503 UNAVAILABLE high demand")
            if model == sv.GEMINI_NEXT[1]:
                raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 20")
            part = NS(text="34 sidewalks.", thought=False, function_call=None)
            return NS(candidates=[NS(content=genai.types.Content(role="model", parts=[genai.types.Part(text=part.text)]))])

    monkeypatch.setattr(genai, "Client", lambda api_key: NS(models=Models()))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("URBANSTYLE_GEMINI_MODEL", sv.GEMINI_NEXT[0])
    monkeypatch.setattr(sv.Agent, "_anthropic_key", staticmethod(lambda: None))

    class Area:
        name, epsg = "test", "EPSG:32610"
        schema = lambda self: "work.part"
    ag = sv.Agent(Area())
    r = ag.ask("s", "Narrow sidewalks?")
    assert r["answer"] == "34 sidewalks."
    assert calls == sv.GEMINI_NEXT[:3] and sv.GEMINI_NEXT[1] in ag.gused and sv.GEMINI_NEXT[0] not in ag.gused
