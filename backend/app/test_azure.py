import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

response = client.chat.completions.create(
    model="Phi-4",
    messages=[
        {"role": "user", "content": "Say hello and confirm you are Phi-4 running on Azure."}
    ],
)

print(response.choices[0].message.content)