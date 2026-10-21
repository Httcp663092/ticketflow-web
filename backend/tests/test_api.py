import os
os.environ["SECRET_KEY"]="test-key-only-not-for-production-123456789"
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, database
from app.models import User
from app.main import app, passwords
import pytest
@pytest.fixture()
def client():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine); sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        for name,role in [("alice","requester"),("bob","requester"),("agent","agent"),("admin","admin")]:
            db.add(User(username=name,password_hash=passwords.hash("test-password"),role=role))
        db.commit()
    def override():
        with sessions() as db: yield db
    app.dependency_overrides[database]=override
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear(); engine.dispose()
def auth(c,name):
    return {"Authorization":"Bearer "+c.post("/api/auth/login",json={"username":name,"password":"test-password"}).json()["access_token"]}
def create(c,headers):
    return c.post("/api/tickets",headers=headers,json={"title":"ERP unavailable","description":"Cannot open ERP","category":"erp","priority":"urgent"})
def test_auth_and_validation(client):
    assert client.get("/api/health").status_code==200
    assert client.get("/api/tickets").status_code in [401,403]
    assert client.post("/api/auth/login",json={"username":"alice","password":"bad"}).status_code==401
    assert client.post("/api/tickets",headers=auth(client,"alice"),json={"title":""}).status_code==422
def test_isolation_and_workflow(client):
    alice=auth(client,"alice"); bob=auth(client,"bob"); agent=auth(client,"agent")
    result=create(client,alice); assert result.status_code==201
    path=f"/api/tickets/{result.json()['id']}"
    assert client.get(path,headers=bob).status_code==404
    assert client.get("/api/tickets",headers=bob).json()==[]
    assert client.post(path+"/comments",headers=bob,json={"message":"intrusion"}).status_code==404
    assert client.patch(path+"/status",headers=alice,json={"status":"in_progress"}).status_code==403
    assert client.patch(path+"/status",headers=agent,json={"status":"closed"}).status_code==409
    for state in ["in_progress","resolved"]:
        assert client.patch(path+"/status",headers=agent,json={"status":state}).status_code==200
    assert client.patch(path+"/status",headers=alice,json={"status":"closed"}).status_code==200
    assert len(client.get(path+"/events",headers=alice).json())==4
def test_assignment_comments_and_search(client):
    alice=auth(client,"alice"); admin=auth(client,"admin")
    ticket=create(client,alice).json(); path=f"/api/tickets/{ticket['id']}"
    assert client.patch(path+"/assignee",headers=alice,json={"assignee_id":3}).status_code==403
    assert client.patch(path+"/assignee",headers=admin,json={"assignee_id":1}).status_code==422
    assert client.patch(path+"/assignee",headers=admin,json={"assignee_id":3}).json()["assignee_id"]==3
    assert client.post(path+"/comments",headers=alice,json={"message":"Updated details"}).status_code==201
    assert len(client.get("/api/tickets?q=ERP",headers=alice).json())==1
    assert client.get("/api/tickets?q=missing",headers=alice).json()==[]
