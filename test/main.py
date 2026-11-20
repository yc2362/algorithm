import os
from fastapi import FastAPI

app = FastAPI(title="Connection Test Server")

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Connection successful!",
        "service": "test-project"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
