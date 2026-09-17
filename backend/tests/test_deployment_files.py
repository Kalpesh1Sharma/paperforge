"""Static safety checks for the single-instance Docker deployment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_connects_frontend_backend_health_and_persistent_storage() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "backend:" in compose and "frontend:" in compose
    assert "condition: service_healthy" in compose
    assert "paperforge-data:/data/reports" in compose
    assert "VITE_API_BASE_URL" in compose
    assert "GEMINI_API_KEY=" not in compose
    assert "GROQ_API_KEY=" not in compose


def test_container_files_and_keyless_demo_profile_are_present() -> None:
    backend = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    demo = (ROOT / "backend" / "demo.env").read_text(encoding="utf-8")

    assert "uvicorn" in backend and "USER pwuser" in backend
    assert "npm run build" in frontend and "nginx" in frontend
    assert "AI_PROVIDER_ORDER=deterministic" in demo
    assert "API_KEY=" not in demo
