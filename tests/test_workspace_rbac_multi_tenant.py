from __future__ import annotations

import pytest
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import sessionmaker, declarative_base

from server.workspace.scoping import register_workspace_scoping
from server.workspace.rbac import WorkspaceRole, role_allows, can_manage_members, can_write


Base = declarative_base()


class DummyResource(Base):
    __tablename__ = "dummy_resources"
    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), nullable=False, index=True)
    value = Column(String(50), nullable=False)


@pytest.fixture()
def db():
    register_workspace_scoping()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    return SessionLocal


def test_role_hierarchy():
    assert role_allows(WorkspaceRole.owner, [WorkspaceRole.admin])
    assert role_allows(WorkspaceRole.admin, [WorkspaceRole.member])
    assert not role_allows(WorkspaceRole.viewer, [WorkspaceRole.member])
    assert can_manage_members(WorkspaceRole.owner)
    assert can_manage_members(WorkspaceRole.admin)
    assert not can_manage_members(WorkspaceRole.member)
    assert can_write(WorkspaceRole.member)
    assert not can_write(WorkspaceRole.viewer)


def test_scoping_select_isolated(db):
    s = db()
    s.add(DummyResource(id="a", workspace_id="ws1", value="one"))
    s.add(DummyResource(id="b", workspace_id="ws2", value="two"))
    s.commit()

    s1 = db()
    s1.info["workspace_id"] = "ws1"
    rows = s1.query(DummyResource).all()
    assert [r.id for r in rows] == ["a"]

    s2 = db()
    s2.info["workspace_id"] = "ws2"
    rows = s2.query(DummyResource).all()
    assert [r.id for r in rows] == ["b"]


def test_scoping_update_delete_isolated(db):
    s = db()
    s.add(DummyResource(id="a", workspace_id="ws1", value="one"))
    s.add(DummyResource(id="b", workspace_id="ws2", value="two"))
    s.commit()

    s1 = db()
    s1.info["workspace_id"] = "ws1"
    s1.query(DummyResource).update({DummyResource.value: "x"})
    s1.commit()

    s = db()
    all_rows = {r.id: r.value for r in s.query(DummyResource).all()}
    assert all_rows["a"] == "x"
    assert all_rows["b"] == "two"

    s2 = db()
    s2.info["workspace_id"] = "ws2"
    s2.query(DummyResource).filter(DummyResource.id == "a").delete()
    s2.commit()

    s = db()
    ids = sorted([r.id for r in s.query(DummyResource).all()])
    assert ids == ["a", "b"], "ws2 scoped delete should not delete ws1 row"
