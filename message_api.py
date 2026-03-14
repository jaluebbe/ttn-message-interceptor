#!venv/bin/python3
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from routers import location, ttn_messages

app = FastAPI(default_response_class=ORJSONResponse)
app.include_router(ttn_messages.router)
app.include_router(location.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)

