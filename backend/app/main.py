from fastapi import FastAPI

app = FastAPI(
    title="PaperForge API",
    description="AI-powered research workspace backend.",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "Welcome to PaperForge API!"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "PaperForge",
        "version": "0.1.0",
    }