"""Run on the ECS host after route activation; creates one closed verification ticket."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://8.159.144.194/ticketflow/api"
credentials = json.loads(Path("/opt/ticketflow/shared/bootstrap.json").read_text())
token = None

def call(method, path, body=None, raw=False):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    with urlopen(Request(BASE + path, data=body, headers=headers, method=method), timeout=20) as response:
        data = response.read()
    return data if raw else json.loads(data)

token = call("POST", "/auth/login", credentials)["access_token"]
assert call("GET", "/auth/me")["role"] == "admin"
t = call("POST", "/tickets", {"title":"上线验证工单（自动验收）", "description":"验证生产数据库、评论、附件与状态流转，验证完成后关闭。", "category":"operations", "priority":"low"})
id = t["id"]
path = f"/tickets/{id}"
call("POST", path + "/comments", {"message":"生产上线验收：数据库读写正常。", "internal":True})
payload = b"TicketFlow deployment verification\n"
a = call("POST", path + "/attachments?filename=deployment-check.txt", payload)
assert call("GET", path + "/attachments/" + str(a["id"]), raw=True) == payload
for status in ["in_progress", "resolved", "closed"]:
    t = call("GET", path)
    t = call("PATCH", path + "/status", {"status":status, "version":t["version"]})
assert t["status"] == "closed"
assert len(call("GET", path + "/events")) >= 5
print("PRODUCTION_SMOKE_OK ticket=" + str(id) + " status=closed; no credentials logged")
