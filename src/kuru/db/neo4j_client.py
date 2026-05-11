"""Neo4j client — schema setup and PLO graph population."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

from dotenv import load_dotenv
from neo4j import GraphDatabase, Session

load_dotenv()

# ─────────────────────────────────────────
# Connection
# ─────────────────────────────────────────

def get_driver():
    uri      = os.environ["NEO4J_URI"]
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(username, password))


@contextmanager
def session_ctx() -> Generator[Session, None, None]:
    driver = get_driver()
    try:
        with driver.session() as session:
            yield session
    finally:
        driver.close()


# ─────────────────────────────────────────
# Schema setup (idempotent)
# ─────────────────────────────────────────

CONSTRAINTS = [
    "CREATE CONSTRAINT faculty_id IF NOT EXISTS FOR (f:Faculty) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT plo_id IF NOT EXISTS FOR (p:PLO) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (s:SkillCluster) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT course_code IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE",
]


def setup_schema() -> None:
    with session_ctx() as s:
        for cypher in CONSTRAINTS:
            s.run(cypher)


# ─────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────

def upsert_faculty(session: Session, faculty_id: str, name_th: str) -> None:
    session.run(
        "MERGE (f:Faculty {id: $id}) SET f.name_th = $name_th",
        id=faculty_id, name_th=name_th,
    )


def upsert_skill_cluster(session: Session, name: str, riasec_dim: str) -> None:
    session.run(
        "MERGE (s:SkillCluster {name: $name}) SET s.riasec_dim = $riasec_dim",
        name=name, riasec_dim=riasec_dim,
    )


def upsert_plo_with_relationships(
    session: Session,
    plo_id: str,
    plo_text: str,
    faculty_id: str,
    skill_cluster_names: list[str],
) -> None:
    """Create PLO node and wire Faculty→PLO and PLO→SkillCluster edges."""
    session.run(
        """
        MERGE (p:PLO {id: $plo_id})
        SET p.text = $plo_text
        WITH p
        MATCH (f:Faculty {id: $faculty_id})
        MERGE (f)-[:HAS_PLO]->(p)
        """,
        plo_id=plo_id, plo_text=plo_text, faculty_id=faculty_id,
    )
    for skill in skill_cluster_names:
        session.run(
            """
            MATCH (p:PLO {id: $plo_id})
            MATCH (s:SkillCluster {name: $skill})
            MERGE (p)-[:DEVELOPS]->(s)
            """,
            plo_id=plo_id, skill=skill,
        )


def ingest_program_plos(
    faculty_id: str,
    faculty_name_th: str,
    plos: list[dict[str, Any]],
) -> None:
    """Write a full Faculty + PLO + SkillCluster subgraph.

    Each PLO dict must have:
      - plo_id: str
      - plo_text: str
      - skill_clusters: list[dict] with keys 'name' and 'riasec_dim'
    """
    with session_ctx() as s:
        upsert_faculty(s, faculty_id, faculty_name_th)
        for plo in plos:
            for skill in plo.get("skill_clusters", []):
                upsert_skill_cluster(s, skill["name"], skill.get("riasec_dim", ""))
            upsert_plo_with_relationships(
                s,
                plo_id=plo["plo_id"],
                plo_text=plo["plo_text"],
                faculty_id=faculty_id,
                skill_cluster_names=[sk["name"] for sk in plo.get("skill_clusters", [])],
            )


def upsert_course(session: Session, course_code: str, course_name: str, faculty_id: str) -> None:
    session.run(
        """
        MERGE (c:Course {code: $code})
        SET c.name = $name
        WITH c
        MATCH (f:Faculty {id: $faculty_id})
        MERGE (f)-[:HAS_COURSE]->(c)
        """,
        code=course_code, name=course_name, faculty_id=faculty_id,
    )


def upsert_course_plo_edge(
    session: Session,
    course_code: str,
    plo_id: str,
    level: str,
) -> None:
    """Wire (Course)-[:ADDRESSES {level}]->(PLO). level is 'X' or 'X*'."""
    session.run(
        """
        MATCH (c:Course {code: $course_code})
        MATCH (p:PLO {id: $plo_id})
        MERGE (c)-[r:ADDRESSES]->(p)
        SET r.level = $level
        """,
        course_code=course_code, plo_id=plo_id, level=level,
    )


def ingest_plo_course_mappings(
    faculty_id: str,
    mappings: list[dict[str, Any]],
) -> None:
    """Write Course nodes and ADDRESSES edges from ตารางผลลัพธ์การเรียนรู้ระดับรายวิชา.

    Each mapping dict must have:
      - course_code: str
      - course_name: str
      - plo_mapping: list[dict] with keys 'plo_id' and 'level' ('X' or 'X*')
    """
    with session_ctx() as s:
        for m in mappings:
            upsert_course(s, m["course_code"], m["course_name"], faculty_id)
            for pm in m.get("plo_mapping", []):
                plo_id = f"{faculty_id}_{pm['plo_id']}"
                upsert_course_plo_edge(s, m["course_code"], plo_id, pm.get("level", "X"))


# ─────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────

def get_plos_for_faculty(faculty_id: str) -> list[dict[str, Any]]:
    with session_ctx() as s:
        result = s.run(
            """
            MATCH (f:Faculty {id: $faculty_id})-[:HAS_PLO]->(p:PLO)
            OPTIONAL MATCH (p)-[:DEVELOPS]->(sk:SkillCluster)
            RETURN p.id as plo_id, p.text as plo_text,
                   collect(sk.name) as skill_clusters
            """,
            faculty_id=faculty_id,
        )
        return [dict(r) for r in result]


def get_courses_for_plo(plo_id: str) -> list[dict[str, Any]]:
    with session_ctx() as s:
        result = s.run(
            """
            MATCH (c:Course)-[r:ADDRESSES]->(p:PLO {id: $plo_id})
            RETURN c.code as course_code, c.name as course_name, r.level as level
            ORDER BY r.level DESC, c.code
            """,
            plo_id=plo_id,
        )
        return [dict(r) for r in result]


def get_plos_for_course(course_code: str) -> list[dict[str, Any]]:
    with session_ctx() as s:
        result = s.run(
            """
            MATCH (c:Course {code: $course_code})-[r:ADDRESSES]->(p:PLO)
            RETURN p.id as plo_id, p.text as plo_text, r.level as level
            ORDER BY r.level DESC, p.id
            """,
            course_code=course_code,
        )
        return [dict(r) for r in result]
