from app.services.parsing.heuristic_parser import parse_heuristic, parse_prisma, parse_sql
from app.services.parsing.python_parser import parse_python
from app.services.parsing.ts_parser import parse_typescript

PY = '''
"""Orders API."""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from .db import Base, get_db
from ..auth import get_current_user

router = APIRouter(prefix="/orders")
TIMEOUT = int(os.getenv("ORDER_TIMEOUT", "5"))


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    user = relationship("User", back_populates="orders")


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="missing")
    return order


@router.post("", status_code=201)
def create(payload: OrderIn, db=Depends(get_db)):
    db.add(Order(**payload.dict()))
    db.commit()
'''


def test_python_symbols_routes_models():
    r = parse_python("app/api/orders.py", PY)
    m = r.module
    assert m.parse_ok and m.docstring == "Orders API."
    names = {s.name: s for s in m.symbols}
    assert names["get_order"].is_async and names["get_order"].kind == "function"
    assert names["Order"].kind == "class" and names["Order"].bases == ["Base"]
    assert ("ORDER_TIMEOUT", 11) in m.env_vars
    routes = {(x.method, x.path): x for x in r.routes}
    g = routes[("GET", "/{order_id}")]
    assert g.auth == ["get_current_user"] and g.response_model == "OrderOut" and 404 in g.status_codes and g.router_var == "router"
    assert routes[("POST", "")].body_model == "OrderIn" and routes[("POST", "")].status_codes == [201]
    assert r.router_prefixes == {"router": "/orders"}
    model = r.db_models[0]
    assert model.table == "orders"
    fields = {f.name: f for f in model.fields}
    assert fields["id"].primary_key and fields["code"].unique and fields["code"].nullable is False
    assert fields["user_id"].foreign_key == "users.id" and fields["user_id"].index
    assert model.relationships[0]["target"] == "User"
    ops = {o.operation for o in r.db_operations}
    assert {"orm_query", "insert", "transaction"} <= ops
    rel = [i for i in m.imports if i.module.startswith("/")]
    assert {i.module for i in rel} == {"/app.api.db", "/app.auth"}
    assert "api-routes" in m.roles and "data-model" in m.roles


def test_python_syntax_error_is_reported():
    r = parse_python("bad.py", "def broken(:\n  pass")
    assert not r.module.parse_ok and "SyntaxError" in r.module.parse_error


def test_flask_and_django_routes():
    flask = parse_python("app.py", "from flask import Flask, Blueprint\nbp = Blueprint('b', __name__, url_prefix='/b')\n@bp.route('/x', methods=['GET','POST'])\ndef x():\n    return ''\n")
    assert {(r.method, r.path, r.framework) for r in flask.routes} == {("GET", "/x", "Flask"), ("POST", "/x", "Flask")}
    assert flask.router_prefixes["bp"] == "/b"
    dj = parse_python("shop/urls.py", "from django.urls import path\nfrom . import views\nurlpatterns = [path('items/<int:pk>/', views.detail), path('admin/', include('x'))]\n")
    assert [(r.path, r.handler) for r in dj.routes] == [("/items/<int:pk>/", "views.detail")]


TS = '''
import express from "express";
import { requireAuth } from "./middleware/auth";
import axios from "axios";
const router = express.Router();
const api = axios.create({ baseURL: "/" });
export interface User { id: number; name: string }
export type Id = string;
export enum Role { Admin }
export async function listUsers(req, res) {
  try { await pool.query(`SELECT * FROM users WHERE id = ${req.params.id}`); } catch (e) { throw new Error("x"); }
}
router.get("/users/:id", requireAuth, listUsers);
router.post("/users", async (req, res) => { await prisma.user.create({ data: req.body }); });
export const fetchItems = () => api.get("/api/items");
export default function Page() { return <div>{process.env.NEXT_PUBLIC_X}</div>; }
'''


def test_typescript_extraction():
    r = parse_typescript("server/routes.tsx", TS)
    kinds = {s.name: s.kind for s in r.module.symbols}
    assert kinds["User"] == "interface" and kinds["Id"] == "type" and kinds["Role"] == "enum"
    assert kinds["listUsers"] == "function" and kinds["Page"] == "component"
    routes = {(x.method, x.path): x for x in r.routes}
    assert routes[("GET", "/users/:id")].auth == ["requireAuth"]
    assert routes[("POST", "/users")].calls == ["prisma.user.create"]
    assert not any(x.path == "/api/items" for x in r.routes), "axios client call must not be treated as a route"
    assert [(c.method, c.url) for c in r.client_calls] == [("GET", "/api/items")]
    ops = {(o.operation, o.raw_sql) for o in r.db_operations}
    assert ("insert", False) in ops and ("raw_sql", True) in ops
    assert ("NEXT_PUBLIC_X", 16) in r.module.env_vars
    assert {i.module for i in r.module.imports} == {"express", "./middleware/auth", "axios"}


def test_nextjs_route_handlers():
    r = parse_typescript("src/app/api/teams/[teamId]/members/route.ts", "export async function GET() {}\nexport async function DELETE() {}\n")
    assert sorted((x.method, x.path) for x in r.routes) == [("DELETE", "/api/teams/:teamId/members"), ("GET", "/api/teams/:teamId/members")]
    pages = parse_typescript("pages/api/health.ts", "export default function handler(req, res) { if (req.method === 'POST') {} }")
    assert [(x.method, x.path) for x in pages.routes] == [("POST", "/api/health")]


def test_nestjs_controller():
    src = "@Controller('cats')\nexport class CatsController {\n  @Get(':id')\n  @UseGuards(AuthGuard)\n  findOne() { return this.svc.find(); }\n}\n"
    r = parse_typescript("src/cats.controller.ts", src)
    assert [(x.method, x.path, x.handler) for x in r.routes] == [("GET", "/cats/:id", "CatsController.findOne")]


def test_heuristic_go_and_java():
    go = parse_heuristic("main.go", 'package main\nimport "github.com/gin-gonic/gin"\nfunc main() {\n r := gin.Default()\n r.GET("/ping", ping)\n}\nfunc ping(c *gin.Context) {\n c.JSON(200, nil)\n}\n', "Go")
    assert {s.name for s in go.module.symbols} >= {"main", "ping"}
    assert [(x.method, x.path, x.handler) for x in go.routes] == [("GET", "/ping", "ping")]
    java = parse_heuristic("src/main/java/a/UserController.java",
                           '@RestController\n@RequestMapping("/users")\npublic class UserController {\n  @GetMapping("/{id}")\n  public User get(@PathVariable Long id) { return null; }\n}\n', "Java")
    assert [(x.method, x.path) for x in java.routes] == [("GET", "/users/{id}")]
    assert java.module.parser == "heuristic-java"


def test_prisma_and_sql():
    prisma = parse_prisma("schema.prisma", 'model User {\n  id Int @id @default(autoincrement())\n  email String @unique\n  posts Post[]\n}\nmodel Post {\n  id Int @id\n  authorId Int\n  author User @relation(fields: [authorId], references: [id])\n}\n')
    users, posts = prisma.db_models
    assert users.fields[0].primary_key and users.fields[1].unique
    assert users.relationships[0]["kind"] == "one_to_many"
    assert next(f for f in posts.fields if f.name == "authorId").foreign_key == "User.id"
    sql = parse_sql("db.sql", "CREATE TABLE orders (\n id SERIAL PRIMARY KEY,\n user_id INT NOT NULL REFERENCES users(id),\n note TEXT\n);\nCREATE INDEX idx_o ON orders(user_id);\n")
    t = sql.db_models[0]
    cols = {f.name: f for f in t.fields}
    assert cols["id"].primary_key and cols["user_id"].foreign_key == "users.id" and cols["user_id"].nullable is False
    assert t.indexes == ["idx_o(user_id)"]
