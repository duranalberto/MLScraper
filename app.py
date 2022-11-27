from typing import List
import uvicorn
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
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


app = FastAPI()
manager = ConnectionManager()
scrapper = Scrapper(manager.broadcast)


@app.get("/api/search")
def search():
    return scrapper.get_list()


@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)


@app.on_event('startup')
async def initial_task():
    asyncio.create_task(scrapper.scrape())


@app.on_event("shutdown")
async def shutdown_event():
    manager.disconnect_all()
    print('Good bye')

app.mount("/", StaticFiles(directory="static",html = True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=80, loop='asyncio')