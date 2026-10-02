from fastapi import FastAPI

# Create our API application.
app = FastAPI(title="Audio Notes API")


# Respond to GET requests sent to /live.
@app.get("/live")
async def live():
    return {"status": "ok"}