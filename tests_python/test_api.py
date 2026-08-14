from fastapi.testclient import TestClient

from metrichit_os.api import app, router


client = TestClient(app)


def test_health_is_explicitly_read_only():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "backend": "python-fastapi", "read_only": True
    }


def test_read_only_endpoints_use_versioned_routes():
    for route in (
        "/api/v1/context",
        "/api/v1/memory/summary",
        "/api/v1/editorial/status",
    ):
        response = client.get(route)
        assert response.status_code == 200
        assert "C:\\" not in response.text
        assert str(response.request.url).startswith("http://testserver/")
        assert all(value is not None for value in response.json().values())


def test_only_the_four_declared_get_routes_are_exposed():
    app_routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    router_routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert app_routes == {("/health", "GET")}
    assert router_routes == {
        ("/api/v1/context", "GET"),
        ("/api/v1/memory/summary", "GET"),
        ("/api/v1/editorial/status", "GET"),
    }
    assert client.get("/openapi.json").status_code == 404


def test_mutating_methods_are_not_exposed():
    for route in (
        "/api/v1/context",
        "/api/v1/memory/summary",
        "/api/v1/editorial/status",
    ):
        for method in (client.post, client.put, client.patch, client.delete):
            assert method(route).status_code == 405
