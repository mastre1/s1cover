import asf_search as asf
import pytest
import requests

from s1cover import query


@pytest.mark.parametrize(
    "proxy_error", [requests.exceptions.ProxyError, requests.exceptions.InvalidSchema]
)
def test_auto_bypasses_unusable_system_proxy(monkeypatch, proxy_error):
    attempts = []
    monkeypatch.setattr(query, "effective_proxy", lambda: "http://localhost:1")

    def search(**kwargs):
        session = kwargs["session"]
        attempts.append(session.trust_env)
        if session.trust_env:
            raise proxy_error("Unavailable")
        results = asf.ASFSearchResults()
        results.searchComplete = True
        return results

    monkeypatch.setattr(asf, "search", search)
    aoi = query.aoi_options([0, 0, 1, 1], None)
    assert query.search_tracks(aoi, start=None, end=None, max_results=5) == []
    assert attempts == [True, False]


def test_manual_proxy_uses_only_explicit_address():
    connection = query.Connection("proxy", "127.0.0.1:7890")
    with query.CatalogSession(connection, trust_env=False) as session:
        options = session.merge_environment_settings(
            "https://cmr.earthdata.nasa.gov", {}, None, None, None
        )
        assert options["proxies"]["https"] == "http://127.0.0.1:7890"
        prepared = session.prepare_request(
            requests.Request("GET", "https://cmr.earthdata.nasa.gov")
        )
        assert "Authorization" not in prepared.headers


def test_manual_proxy_rejects_credentials():
    with pytest.raises(ValueError):
        query.Connection("proxy", "http://user:secret@localhost:7890")


def test_catalog_does_not_follow_redirects_with_geometry(monkeypatch):
    calls = []

    def request(_session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 307
        response.headers["Location"] = "https://example.org/elsewhere"
        return response

    monkeypatch.setattr(asf.ASFSession, "request", request)
    with (
        query.CatalogSession(
            query.Connection("direct"), trust_env=False, geometry=b"{}"
        ) as session,
        pytest.raises(query.QueryError, match="redirect"),
    ):
        session.post(query.CATALOG_URL)
    assert len(calls) == 1
    assert calls[0][2]["allow_redirects"] is False
    assert calls[0][2]["files"]["shapefile"][1] == b"{}"
