from typing import List
from uvicorn import run as uvicorn_run
from asyncio import create_task as asyncio_create_task
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from scrapper import Scrapper


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print('New client connected')
        while True:
            try:
                await websocket.receive_text()
            except Exception as e:
                self.disconnect(websocket)
                print('Error at websocket listener:', e)
                break

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    def disconnect_all(self):
        for connection in self.active_connections:
            self.disconnect(connection)

    async def broadcast(self, message: str):
        print('Broadcasting: ' + message)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                self.disconnect(connection)

connection = ConnectionManager()
scrapper = Scrapper(connection.broadcast)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio_create_task(scrapper.run())
    yield
    connection.disconnect_all()
    print('Good bye')


app = FastAPI(lifespan=lifespan)

@app.get("/api/search")
def search():
    return scrapper.get_list()

@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await connection.connect(websocket)


app.mount("/", StaticFiles(directory="static",html = True), name="static")


if __name__ == "__main__":
    uvicorn_run(app, host="0.0.0.0", port=80, loop='asyncio')