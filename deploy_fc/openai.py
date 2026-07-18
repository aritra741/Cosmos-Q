import json
import urllib.request
import urllib.error

class OpenAI:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.embeddings = Embeddings(self)
        self.chat = Chat(self)

class Embeddings:
    def __init__(self, client):
        self.client = client

    def create(self, model, input, dimensions=1024, encoding_format="float"):
        url = f"{self.client.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model,
            "input": input
        }
        if dimensions is not None:
            data["dimensions"] = dimensions
            
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                return CreateEmbeddingResponse(resp_data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            raise RuntimeError(f"Qwen Embedding API failed: {e.code} - {err_body}")

class CreateEmbeddingResponse:
    def __init__(self, data):
        self.data = [EmbeddingObject(item) for item in data.get("data", [])]

class EmbeddingObject:
    def __init__(self, item):
        self.embedding = item.get("embedding", [])
        self.index = item.get("index", 0)

class Chat:
    def __init__(self, client):
        self.completions = Completions(client)

class Completions:
    def __init__(self, client):
        self.client = client

    def create(self, model, messages, extra_body=None):
        url = f"{self.client.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model,
            "messages": messages
        }
        if extra_body:
            data.update(extra_body)
            
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                return CreateChatCompletionResponse(resp_data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            raise RuntimeError(f"Qwen Completions API failed: {e.code} - {err_body}")

class CreateChatCompletionResponse:
    def __init__(self, data):
        self.choices = [Choice(item) for item in data.get("choices", [])]

class Choice:
    def __init__(self, item):
        self.message = Message(item.get("message", {}))

class Message:
    def __init__(self, msg):
        self.content = msg.get("content", "")
