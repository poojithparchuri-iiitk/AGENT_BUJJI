from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def read_root():
    return {"message": "Agent Bujji backend is running"}

@app.post("/chat")
def chat(request: ChatRequest):
    response = client.chat.completions.create(
        model="Phi-4",
        messages=[
            {"role": "user", "content": request.message}
        ],
    )
    reply = response.choices[0].message.content
    return {"reply": reply}